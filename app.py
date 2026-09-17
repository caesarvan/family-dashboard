"""Two-person household dashboard. Financial and calendar integrations are explicit."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

from flask import Flask, abort, g, jsonify, request, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from cloud_accounts import register_accounts
from shopping_media import register_media, validate_photo_ids, sync_photo_refs
from finance_baseline import register_finance_baseline, shared_baselines
from finance_source_bridge import register_finance_source_bridge
from household_spaces import register_preferences, register_spaces
from home_assistant import register_assistant
from journey_workflows import register_journeys
from journey_documents import register_journey_documents
from journey_places import register_journey_places
from finance_hub import register_finance_hub
from calendar_publish import register_calendar_publish
from dashboard_preferences import register_dashboard_layout
from data_portability import register_portability
from task_publish import register_task_publish
from member_sessions import MemberSessions, register_sessions
from tv_display import stored_layout, validate_layout
from sync_health import register_sync_health
from shopping_settlement import register_shopping_settlement
from household_routines import register_routines
from household_media import register_media_library
from media_playback import register_media_playback
from inventory_api import register_inventory
from frontend_runtime import register_frontend_runtime

TZ = ZoneInfo("Asia/Shanghai")
ROOT = Path(__file__).parent
KINDS = {"tasks", "shopping", "events", "trips"}
DEFAULT_FINANCE = {
    "wallet": 0, "livingSpent": 0, "livingBudget": 620000,
    "travelSaved": 0, "travelAnnualBudget": 10400000, "longterm": 0,
    "reserveTarget": 1000000, "upcomingPayments": 0, "contributionPercent": 50,
    "confirmedAt": "", "note": "", "revision": 1,
}


class Problem(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def now():
    return datetime.now(TZ).isoformat(timespec="seconds")


def create_app(config=None):
    app = Flask(__name__, static_folder=None)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        DATA_DIR=os.environ.get("DATA_DIR", str(ROOT / "data")),
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "1") == "1",
        # A delayed read must not reinstall its old login after this browser
        # changes members. Real session mutations still issue their cookie.
        SESSION_REFRESH_EACH_REQUEST=False,
        PERMANENT_SESSION_LIFETIME=timedelta(days=30), MAX_CONTENT_LENGTH=600_000,
    )
    for key in ('PUBLIC_ORIGIN', 'MICROSOFT_CLIENT_ID', 'MICROSOFT_CLIENT_SECRET', 'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET'):
        if os.environ.get(key):
            app.config[key] = os.environ[key]
    for key in ('ASSISTANT_PROVIDER', 'NVIDIA_API_KEY', 'NVIDIA_MODEL', 'OPENAI_API_KEY', 'OPENAI_MODEL'):
        if key in os.environ:
            app.config[key] = os.environ[key]
    if config:
        app.config.update(config)
    if not app.config["SECRET_KEY"]:
        raise RuntimeError("SECRET_KEY must be configured")
    if os.environ.get("TRUST_PROXY") == "1":
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    data_dir = Path(app.config["DATA_DIR"])
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "household.sqlite3"

    def db():
        if "db" not in g:
            g.db = sqlite3.connect(db_path, timeout=15)
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys=ON")
        return g.db

    @app.teardown_appcontext
    def close_db(error=None):
        if "db" in g:
            g.db.close()

    def initialize():
        con = db()
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
          name TEXT NOT NULL, password TEXT NOT NULL, auth_version INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS entities(id TEXT PRIMARY KEY, kind TEXT NOT NULL,
          data TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS entities_kind ON entities(kind);
        CREATE TABLE IF NOT EXISTS settings(id TEXT PRIMARY KEY, data TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS private_finance(owner TEXT PRIMARY KEY REFERENCES users(id), data TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY, code TEXT UNIQUE, secret_hash TEXT NOT NULL,
          name TEXT NOT NULL DEFAULT '', focus TEXT, approved INTEGER NOT NULL DEFAULT 0,
          expires REAL NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts(ip TEXT NOT NULL, category TEXT NOT NULL, stamp REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT,
          action TEXT NOT NULL, target TEXT, stamp TEXT NOT NULL);
        """)
        # Serialize compatibility columns across concurrently starting app/worker.
        con.execute('BEGIN IMMEDIATE')
        device_columns = {row[1] for row in con.execute('PRAGMA table_info(devices)')}
        if 'calendar_view' not in device_columns:
            con.execute("ALTER TABLE devices ADD COLUMN calendar_view TEXT NOT NULL DEFAULT 'today'")
        if 'revision' not in device_columns:
            con.execute('ALTER TABLE devices ADD COLUMN revision INTEGER NOT NULL DEFAULT 1')
        if 'display_layout' not in device_columns:
            con.execute("ALTER TABLE devices ADD COLUMN display_layout TEXT NOT NULL DEFAULT '{}'")
        con.execute("INSERT OR IGNORE INTO settings(id,data) VALUES('finance',?)", (json.dumps(DEFAULT_FINANCE),))
        con.execute("INSERT OR IGNORE INTO settings(id,data) VALUES('meta',?)", (json.dumps({"revision": 1}),))
        for uid, username, label, env in [
            ("member1", "member1", "我", "MEMBER1_PASSWORD"),
            ("member2", "member2", "伴侣", "MEMBER2_PASSWORD"),
        ]:
            if not con.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
                password = app.config[env] if env in app.config else os.environ.get(env)
                if not password or len(password) < 12:
                    raise RuntimeError(f"{env} must contain at least 12 characters on first start")
                con.execute("INSERT INTO users(id,username,name,password) VALUES(?,?,?,?)",
                            (uid, username, label, generate_password_hash(password)))
        con.commit()

    with app.app_context():
        initialize()

    def audit(action, target=""):
        db().execute("INSERT INTO audit(actor,action,target,stamp) VALUES(?,?,?,?)",
                     (g.actor["id"], action, target, now()))
        db().execute("UPDATE settings SET revision=revision+1 WHERE id='meta'")

    sessions = MemberSessions(app, db_path, Problem)
    app.extensions["member_sessions"] = sessions

    def current_tv_device(con, cookie=None):
        """Re-read the actual pairing secret in the caller's current snapshot."""
        cookie = request.cookies.get('household_tv', '') if cookie is None else cookie
        if not isinstance(cookie, str) or not cookie or len(cookie) > 4096:
            return None
        return con.execute('SELECT * FROM devices WHERE secret_hash=? AND approved=1 AND expires>?',
                           (hashlib.sha256(cookie.encode()).hexdigest(), time.time())).fetchone()

    app.extensions['current_tv_device'] = current_tv_device

    def actor():
        if session.get("uid") and request.headers.get("X-Display-Mode") != "tv":
            member = sessions.actor()
            if member:
                return member
        row = current_tv_device(db())
        if row:
            return {"id": row["id"], "role": "tv", "name": row["name"], "focus": row["focus"], "calendarView": row['calendar_view'], "layout": stored_layout(row['display_layout']), "householdId": app.config.get('HOUSEHOLD_INFO', {}).get('id', 'default')}
        return None

    def require_member():
        if not g.actor:
            raise Problem('请先登录', 401)
        if g.actor["role"] != "member":
            raise Problem("电视是只读设备，请在手机或电脑上操作", 403)

    def body():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise Problem("请提交有效的 JSON 数据")
        return value

    def limited(category, maximum, seconds=600):
        con = db()
        ip = request.remote_addr or "unknown"
        con.execute("DELETE FROM attempts WHERE stamp<?", (time.time()-3600,))
        n = con.execute("SELECT count(*) FROM attempts WHERE ip=? AND category=? AND stamp>?",
                        (ip, category, time.time()-seconds)).fetchone()[0]
        if n >= maximum:
            raise Problem("操作过于频繁，请稍后重试", 429)
        con.execute("INSERT INTO attempts VALUES(?,?,?)", (ip, category, time.time()))
        con.commit()

    @app.before_request
    def guard():
        if request.path == '/api/photos' and request.method == 'POST':
            request.max_content_length = 8_000_000
        if request.path == '/api/journey-documents' and request.method == 'POST':
            request.max_content_length = 7_200_000
        if request.path in {'/api/finance-hub/imports/preview', '/api/finance-hub/imports/confirm', '/api/finance-hub/investments/imports/preview'} and request.method == 'POST':
            request.max_content_length = 3_000_000
        if request.path in {'/api/finance-baseline/imports/preview', '/api/finance-baseline/imports/confirm'} and request.method == 'POST':
            request.max_content_length = 3_000_000
        g.actor = actor()
        if request.path.startswith("/api/"):
            public = {"/api/login", "/api/me", "/api/pair/start", "/api/pair/poll", "/api/auth/providers", "/api/spaces/current", "/api/spaces/redeem"}
            if request.path not in public and not g.actor:
                raise Problem("请先登录", 401)
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                origin = request.headers.get("Origin")
                if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
                    raise Problem("请求来源不匹配", 403)
                if not request.is_json:
                    raise Problem("仅接受 JSON 请求", 415)
                if request.path not in {"/api/login", "/api/pair/start", "/api/pair/poll", "/api/spaces/redeem"}:
                    require_member()
                    token = request.headers.get("X-CSRF-Token", "")
                    if not token or not secrets.compare_digest(token, session.get("csrf", "")):
                        raise Problem("会话已更新，请刷新页面再试", 403)

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.path.startswith(("/api/", "/auth/")):
            response.headers["Cache-Control"] = "no-store"
        if request.path.startswith('/api/journey-documents'):
            response.headers['Cache-Control'] = 'private, no-store'
            if request.path.endswith('/file'):
                response.headers['Content-Security-Policy'] = "default-src 'none'; sandbox; frame-ancestors 'none'"
        if request.path.startswith('/auth/'):
            response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.errorhandler(Problem)
    def problem(error):
        return jsonify(error=error.message), error.status

    @app.errorhandler(413)
    def too_large(error):
        if request.path == '/api/journey-documents':
            return jsonify(error='旅行资料文件过大，请选择不超过 5 MB 的 PDF 或图片'), 413
        if request.path.startswith('/api/finance-baseline/imports/'):
            return jsonify(error='来源更新包过大，请精简来源说明后重新生成'), 413
        return jsonify(error="图片过大，请压缩后重试" if request.path == '/api/photos' else "文件太大，请缩小导出的日期范围"), 413

    @app.get("/healthz")
    def health():
        db().execute("SELECT 1").fetchone()
        return jsonify(status="ok")

    frontend_home = register_frontend_runtime(app, ROOT / 'static')

    @app.get("/")
    @app.get("/tv")
    @app.get("/demo")
    def index():
        if request.path == '/':
            return frontend_home()
        return send_from_directory(ROOT / "static", "index.html")

    @app.get("/static/<path:name>")
    def asset(name):
        if any(part.rstrip(' .').lower() == 'experience' for part in name.replace('\\', '/').split('/')):
            abort(404)
        return send_from_directory(ROOT / "static", name)

    @app.get("/api/me")
    def me():
        if not g.actor:
            sessions.bootstrap()
        return jsonify(user=g.actor, csrf=session.get("csrf") if g.actor and g.actor["role"] == "member" else None)

    @app.post("/api/login")
    def login():
        limited("login", 20)
        data = body()
        claim, browser = sessions.capture(claim=True)
        user = db().execute("SELECT * FROM users WHERE username=?", (str(data.get("username", ""))[:80],)).fetchone()
        password = str(data.get("password", ""))[:256]
        if not user or not check_password_hash(user["password"], password):
            raise Problem("账号或密码不正确", 401)
        with sessions.db() as con:
            con.execute("BEGIN IMMEDIATE")
            cookie = sessions.complete_login(con, user, claim, browser)
        sessions.install(cookie)
        return jsonify(ok=True)

    @app.post("/api/logout")
    def logout():
        with sessions.db() as con:
            con.execute("BEGIN IMMEDIATE")
            current = sessions.current(con)
            sessions.revoke_browser(con, current["browser_hash"], time.time())
        sessions.anonymous()
        response = jsonify(ok=True)
        response.delete_cookie("household_tv")
        return response

    @app.post("/api/profile")
    def profile():
        data = body()
        name = text_field(data.get("name"), "显示名称", 20)
        password = data.get("password", "")
        if password:
            user = db().execute("SELECT * FROM users WHERE id=?", (g.actor["id"],)).fetchone()
            if not check_password_hash(user["password"], str(data.get("currentPassword", ""))):
                raise Problem("当前密码不正确", 403)
            if not isinstance(password, str) or not 12 <= len(password) <= 128:
                raise Problem("新密码需要 12～128 个字符")
            password_hash = generate_password_hash(password)
        con = db()
        con.execute('BEGIN IMMEDIATE')
        current = sessions.current(con)
        cookie = None
        if password:
            # Password verification happened outside the write lock. Re-read the
            # version and credential inside it before changing any member data.
            changed = con.execute("UPDATE users SET password=?,auth_version=auth_version+1 WHERE id=? AND auth_version=?",
                                  (password_hash, current['owner'], user['auth_version'])).rowcount
            if changed != 1:
                raise Problem("账号已更新，请重新登录", 409)
            stamp = time.time()
            rows = con.execute('SELECT browser_hash FROM member_sessions WHERE owner=? AND revoked_at IS NULL', (current['owner'],)).fetchall()
            con.execute('UPDATE member_sessions SET revoked_at=? WHERE owner=? AND revoked_at IS NULL', (stamp, current['owner']))
            sessions.advance(con, [r['browser_hash'] for r in rows], stamp)
            browser = sessions.browser_token(session)
            generation = con.execute('SELECT generation FROM member_session_browsers WHERE browser_hash=?', (current['browser_hash'],)).fetchone()[0]
            claim = {'browserHash': current['browser_hash'], 'generation': generation, 'credentialHash': None}
            fresh = con.execute('SELECT id,auth_version FROM users WHERE id=?', (current['owner'],)).fetchone()
            cookie = sessions.complete_login(con, fresh, claim, browser)
        con.execute("UPDATE users SET name=? WHERE id=?", (name, current['owner']))
        audit("profile")
        con.commit()
        if cookie:
            sessions.install(cookie)
        return jsonify(ok=True)

    register_sessions(app, sessions, Problem, body, require_member)

    @app.get("/api/state")
    def state():
        con = db()
        # Keep display settings and the repaint revision in the same snapshot.
        # The authentication hook may have read this device before a PATCH.
        con.execute('BEGIN')
        display = {'calendarView': 'today', 'focus': g.actor.get('focus')}
        if g.actor['role'] == 'tv':
            screen = current_tv_device(con)
            if not screen or screen['id'] != g.actor['id']:
                raise Problem('电视配对已撤销或过期，请重新配对', 401)
            display = {'focus': screen['focus'], 'calendarView': screen['calendar_view'],
                       'layout': stored_layout(screen['display_layout'])}
        entities = {kind: [] for kind in KINDS}
        for row in db().execute("SELECT * FROM entities ORDER BY updated_at DESC"):
            entities[row["kind"]].append({**json.loads(row["data"]), "id": row["id"], "revision": row["revision"]})
        row = db().execute("SELECT * FROM settings WHERE id='finance'").fetchone()
        finance = {**json.loads(row["data"]), "revision": row["revision"]}
        people = [dict(row) for row in db().execute("SELECT id,name FROM users ORDER BY id")]
        return jsonify(**entities, finance=finance, people=people, updatedAt=now(),
                       household=app.config.get('HOUSEHOLD_INFO') or {'id': 'default', 'slug': 'home', 'name': '我们的家'},
                       wealth=shared_baselines(db()),
                       display=display,
                       revision=db().execute("SELECT revision FROM settings WHERE id='meta'").fetchone()[0],
                       sync=app.extensions['cloud_accounts'].summary(),
                       integrations={"calendar": "账号绑定后自动同步", "finance": "手动核对 · 自动同步待接入"})

    @app.post("/api/items/<kind>")
    def add_item(kind):
        if kind not in KINDS:
            raise Problem("未知的数据类型", 404)
        incoming = body()
        if kind == 'events' and any(key in incoming for key in ('travelTiming', 'startDate', 'endDateExclusive')):
            raise Problem('旅行时间字段只能由旅行计划生成')
        payload = validate(kind, incoming, db)
        if kind == 'tasks':
            source_id = incoming.get('sourceId')
            if source_id is not None and not isinstance(source_id, str):
                raise Problem('清单来源不正确')
            result=app.extensions['cloud_accounts'].task_write(payload, source_id=source_id)
            if result is not None:
                return jsonify(result),201
        count = db().execute("SELECT count(*) FROM entities WHERE kind=?", (kind,)).fetchone()[0]
        if count >= 2500:
            raise Problem("记录数量已达上限，请先整理旧记录")
        uid = secrets.token_hex(12)
        db().execute("INSERT INTO entities(id,kind,data,updated_at) VALUES(?,?,?,?)", (uid, kind, json.dumps(payload), now()))
        if kind == 'shopping':
            sync_photo_refs(db(), uid, payload['photoIds'], g.actor['id'], Problem)
        audit("create_"+kind, uid)
        db().commit()
        return jsonify(id=uid, revision=1), 201

    @app.patch("/api/items/<kind>/<uid>")
    def edit_item(kind, uid):
        row = db().execute("SELECT * FROM entities WHERE id=? AND kind=?", (uid, kind)).fetchone()
        if not row:
            raise Problem("记录不存在，可能已被另一位成员删除", 404)
        data = body()
        if data.get("revision") != row["revision"]:
            raise Problem("另一位成员刚刚更新了这条记录，请刷新后再编辑", 409)
        if json.loads(row['data']).get('sync'):
            if kind != 'tasks':
                raise Problem('日程为只读同步，请在原日历中修改', 403)
            return jsonify(app.extensions['cloud_accounts'].task_write(data, existing=row))
        original = json.loads(row['data'])
        protected_travel = (kind == 'events' and isinstance(original.get('travelTiming'), dict)
                            and db().execute("SELECT 1 FROM journey_links WHERE entity_id=? AND kind='events'", (uid,)).fetchone())
        if kind == 'events':
            if protected_travel:
                for key in ('travelTiming', 'startDate', 'endDateExclusive', 'journeyId', 'tripId', 'workflowKey'):
                    if key in data and data[key] != original.get(key):
                        raise Problem('请在旅行计划中调整该事项的时间与关联', 409)
                for key in ('start', 'end'):
                    if key in data and date_field(data[key], '旅行时间', timestamp=True) != date_field(original[key], '旅行时间', timestamp=True):
                        raise Problem('请在旅行计划中调整该事项的当地时间与时区', 409)
                if 'allDay' in data and (type(data['allDay']) is not bool or data['allDay'] != original.get('allDay')):
                    raise Problem('请在旅行计划中调整该事项的时间类型', 409)
            elif any(key in data for key in ('travelTiming', 'startDate', 'endDateExclusive')):
                raise Problem('旅行时间字段只能由旅行计划生成')
        payload = validate(kind, {**original, **data}, db)
        if protected_travel:
            for key in ('travelTiming', 'startDate', 'endDateExclusive', 'journeyId', 'tripId', 'workflowKey', 'start', 'end', 'allDay'):
                if key in original:
                    payload[key] = original[key]
        n = db().execute("UPDATE entities SET data=?,updated_at=?,revision=revision+1 WHERE id=? AND revision=?",
                         (json.dumps(payload), now(), uid, row["revision"])).rowcount
        if not n:
            raise Problem("记录已更新，请刷新后再试", 409)
        if kind == 'shopping':
            sync_photo_refs(db(), uid, payload['photoIds'], g.actor['id'], Problem)
        audit("update_"+kind, uid)
        db().commit()
        return jsonify(ok=True)

    @app.delete("/api/items/<kind>/<uid>")
    def delete_item(kind, uid):
        data = body()
        row=db().execute('SELECT data FROM entities WHERE id=? AND kind=?',(uid,kind)).fetchone()
        if row and json.loads(row['data']).get('sync'):
            raise Problem('请在原日历或清单中删除，同步后看板会自动更新',403)
        n = db().execute("DELETE FROM entities WHERE id=? AND kind=? AND revision=?", (uid, kind, data.get("revision"))).rowcount
        if not n:
            raise Problem("记录已变更，请刷新后再试", 409)
        if kind == "trips":
            # Keep preparation/history and published calendar entries, removing
            # stale local links so ordinary editors remain usable after deletion.
            for linked in db().execute("SELECT * FROM entities WHERE kind IN ('tasks','shopping','events')").fetchall():
                item = json.loads(linked["data"])
                if item.get("tripId") == uid:
                    item["tripId"] = ""
                    item.pop('journeyId', None)
                    item.pop('workflowKey', None)
                    db().execute("UPDATE entities SET data=?,revision=revision+1,updated_at=? WHERE id=?", (json.dumps(item), now(), linked["id"]))
        audit("delete_"+kind, uid)
        db().commit()
        return jsonify(ok=True)

    @app.put("/api/finance")
    def finance_update():
        data = body()
        payload = {key: amount(data.get(key), key) for key in DEFAULT_FINANCE if key not in {"confirmedAt", "note", "revision", "contributionPercent"}}
        payload["contributionPercent"] = amount(data.get("contributionPercent", 50), "出资比例", maximum=100)
        payload["note"] = text_field(data.get("note", ""), "备注", 500, allow_empty=True)
        payload["confirmedAt"] = now()
        n = db().execute("UPDATE settings SET data=?,revision=revision+1 WHERE id='finance' AND revision=?",
                         (json.dumps(payload), data.get("revision"))).rowcount
        if not n:
            raise Problem("财务记录已被更新，请刷新后核对", 409)
        audit("finance_snapshot")
        db().commit()
        return jsonify(ok=True)

    @app.route("/api/private-finance", methods=["GET", "PUT"])
    def private_finance():
        require_member()
        uid = g.actor["id"]
        row = db().execute("SELECT * FROM private_finance WHERE owner=?", (uid,)).fetchone()
        if request.method == "GET":
            return jsonify({**json.loads(row["data"]), "revision": row["revision"]} if row else {"income": 0, "spent": 0, "budget": 0, "month": now()[:7], "revision": 0})
        data = body()
        payload = {key: amount(data.get(key), key) for key in ["income", "spent", "budget"]}
        month = text_field(data.get("month"), "月份", 7)
        try:
            datetime.strptime(month, "%Y-%m")
        except ValueError:
            raise Problem("月份格式不正确")
        payload.update(month=month, confirmedAt=now())
        if row:
            n = db().execute("UPDATE private_finance SET data=?,revision=revision+1 WHERE owner=? AND revision=?",
                             (json.dumps(payload), uid, data.get("revision"))).rowcount
            if not n:
                raise Problem("个人记录已变更，请刷新", 409)
        else:
            if data.get("revision") != 0:
                raise Problem("个人记录已变更，请刷新", 409)
            db().execute("INSERT INTO private_finance(owner,data) VALUES(?,?)", (uid, json.dumps(payload)))
        audit("private_finance")
        db().commit()
        return jsonify(ok=True)

    @app.post("/api/calendar/import")
    def calendar_import():
        from icalendar import Calendar
        import recurring_ical_events
        data = body()
        owner = data.get("owner", g.actor["id"])
        check_owner(owner, db)
        source = data.get("source", "文件导入")
        if source not in {"Apple", "Google", "Outlook", "文件导入"}:
            raise Problem("未知的日历来源")
        ics = data.get("ics", "")
        if not isinstance(ics, str) or len(ics.encode()) > 500_000:
            raise Problem("日历文件过大")
        start = datetime.now(TZ)-timedelta(days=30)
        try:
            calendar = Calendar.from_ical(ics)
            for component in calendar.walk("VEVENT"):
                rule = component.get("RRULE")
                if rule and str(rule.get("FREQ", [""])[0]) in {"SECONDLY", "MINUTELY", "HOURLY"}:
                    raise ValueError("Sub-daily recurrence is not supported")
            # Skip canceled instances; expand recurring events only within a bounded window.
            events = recurring_ical_events.of(calendar).between(start, start+timedelta(days=396))
        except Exception:
            raise Problem("无法读取日历文件，请导出标准 .ics 文件")
        if len(events) > 500:
            raise Problem("日程过多，请缩小导出范围（每次最多 500 项）")
        prepared = []
        for event in events:
            if str(event.get("STATUS", "")) == "CANCELLED":
                continue
            begin = event.decoded("DTSTART", None)
            if not begin:
                continue
            end = event.decoded("DTEND", begin)
            all_day = not isinstance(begin, datetime)
            def iso(v):
                if isinstance(v, datetime):
                    return (v.replace(tzinfo=TZ) if v.tzinfo is None else v.astimezone(TZ)).isoformat(timespec="seconds")
                return datetime.combine(v, datetime.min.time(), TZ).isoformat(timespec="seconds")
            stable_uid = str(event.get("UID", ""))
            key = hashlib.sha256((owner+"|"+stable_uid+"|"+iso(begin)).encode()).hexdigest()[:24] if stable_uid else secrets.token_hex(12)
            payload = validate("events", {"title": str(event.get("SUMMARY", "未命名安排")), "location": str(event.get("LOCATION", "")),
                          "start": iso(begin), "end": iso(end), "owner": owner, "allDay": all_day, "source": source, "imported": True}, db)
            prepared.append((key, payload))
        existing = {r[0] for r in db().execute("SELECT id FROM entities WHERE kind='events'")}
        if len(existing | {key for key, _ in prepared}) > 2500:
            raise Problem("日程总量已达上限，请先整理旧日程")
        for key, payload in prepared:
            db().execute("INSERT INTO entities(id,kind,data,updated_at) VALUES(?,'events',?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data,revision=entities.revision+1,updated_at=excluded.updated_at",
                         (key, json.dumps(payload), now()))
        audit("calendar_import", str(len(prepared)))
        db().commit()
        return jsonify(imported=len(prepared), note="已导入近 30 天至未来一年；同一成员的相同 UID 与时间自动合并。源日历删除暂需在看板手动删除。")

    @app.post("/api/pair/start")
    def pair_start():
        limited("pair_start", 10)
        key = secrets.token_urlsafe(32)
        code = "".join(secrets.choice("23456789ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(8))
        db().execute("DELETE FROM devices WHERE expires<?", (time.time(),))
        db().execute("INSERT INTO devices(id,code,secret_hash,expires,created_at) VALUES(?,?,?,?,?)",
                     (secrets.token_hex(12), code, hashlib.sha256(key.encode()).hexdigest(), time.time()+600, now()))
        db().commit()
        return jsonify(code=code, secret=key, expiresIn=600)

    @app.post("/api/pair/poll")
    def pair_poll():
        data = body()
        key = str(data.get("secret", ""))[:100]
        row = db().execute("SELECT * FROM devices WHERE secret_hash=? AND expires>?", (hashlib.sha256(key.encode()).hexdigest(), time.time())).fetchone()
        if not row:
            raise Problem("配对码已失效，请刷新电视页面", 410)
        response = jsonify(approved=bool(row["approved"]))
        if row["approved"]:
            response.set_cookie("household_tv", key, secure=app.config["SESSION_COOKIE_SECURE"], httponly=True, samesite="Strict", max_age=90*86400)
        return response

    def device_member(con):
        """Verify the actual credential inside the caller's fresh transaction."""
        require_member()
        current = sessions.current(con)
        original = getattr(g, 'member_session', {})
        if (current['owner'] != g.actor['id'] or current['auth_version'] != g.actor.get('auth_version')
                or current['id'] != original.get('id')
                or g.actor.get('householdId') != app.config.get('HOUSEHOLD_INFO', {}).get('id', 'default')):
            raise Problem('会话已失效，请重新登录', 401)

    @app.post("/api/pair/approve")
    def pair_approve():
        require_member()
        limited("pair_approve", 20)
        data = body()
        code = str(data.get("code", "")).replace(" ", "").upper()
        name = text_field(data.get("name", "家庭电视"), "设备名称", 30)
        view = calendar_view(data.get('calendarView', 'today'))
        con = db()
        con.execute('BEGIN IMMEDIATE')
        try:
            device_member(con)
            focus = data.get("focus", g.actor["id"])
            check_owner(focus, db)
            row = con.execute("SELECT id FROM devices WHERE code=? AND approved=0 AND expires>?", (code, time.time())).fetchone()
            if not row:
                raise Problem("配对码不正确或已过期")
            # A code is consumed once, including competing member approvals.
            n = con.execute("UPDATE devices SET approved=1,code=NULL,name=?,focus=?,calendar_view=?,expires=? WHERE id=? AND code=? AND approved=0 AND expires>?",
                            (name, focus, view, time.time()+90*86400, row['id'], code, time.time())).rowcount
            if not n:
                raise Problem("配对码不正确或已过期")
            audit("pair_device", row['id'])
            device_member(con)
            con.commit()
        except BaseException:
            con.rollback()
            raise
        return jsonify(ok=True)

    @app.get("/api/devices")
    def devices():
        require_member()
        con = db()
        con.execute('BEGIN')
        try:
            device_member(con)
            rows = con.execute("SELECT id,name,focus,calendar_view AS calendarView,revision,created_at,display_layout FROM devices WHERE approved=1 AND expires>?", (time.time(),))
            result = []
            for row in rows:
                item = dict(row)
                item['layout'] = stored_layout(item.pop('display_layout'))
                result.append(item)
        finally:
            con.rollback()
        # A concurrent logout must be observed outside the earlier read snapshot.
        device_member(con)
        return jsonify(result)

    @app.patch('/api/devices/<uid>')
    def edit_device(uid):
        require_member()
        data = body()
        if type(data.get('revision')) is not int or data['revision'] < 1:
            raise Problem('请提供有效的电视设置版本')
        layout = validate_layout(data['layout'], Problem) if 'layout' in data else None
        con = db()
        con.execute('BEGIN IMMEDIATE')
        try:
            device_member(con)
            row = con.execute('SELECT * FROM devices WHERE id=? AND approved=1 AND expires>?', (uid, time.time())).fetchone()
            if not row:
                raise Problem('电视不存在或配对已过期', 404)
            name = text_field(data.get('name', row['name']), '设备名称', 30)
            focus = data.get('focus', row['focus'])
            check_owner(focus, db)
            view = calendar_view(data.get('calendarView', row['calendar_view']))
            layout_json = json.dumps(layout, ensure_ascii=False) if layout is not None else row['display_layout']
            n = con.execute('UPDATE devices SET name=?,focus=?,calendar_view=?,display_layout=?,revision=revision+1 WHERE id=? AND revision=? AND approved=1 AND expires>?',
                             (name, focus, view, layout_json, uid, data['revision'], time.time())).rowcount
            if not n:
                raise Problem('电视设置已更新，请刷新后重试', 409)
            audit('update_device', uid)
            device_member(con)
            con.commit()
        except BaseException:
            con.rollback()
            raise
        return jsonify(ok=True)

    @app.delete("/api/devices/<uid>")
    def revoke_device(uid):
        require_member()
        con = db()
        con.execute('BEGIN IMMEDIATE')
        try:
            device_member(con)
            con.execute("DELETE FROM devices WHERE id=?", (uid,))
            audit("revoke_device", uid)
            device_member(con)
            con.commit()
        except BaseException:
            con.rollback()
            raise
        return jsonify(ok=True)

    register_accounts(app, db, Problem, body, require_member, limited)
    register_media(app, db, Problem, body, limited)
    register_finance_baseline(app, db, require_member, audit)
    register_finance_source_bridge(app, db, Problem, body, require_member, audit)
    register_preferences(app, db, Problem, body, require_member, audit)
    register_dashboard_layout(app, db, Problem, body, require_member, audit)
    register_journeys(app, db, Problem, body, require_member, audit)
    register_journey_documents(app, db, Problem, body, require_member, limited, audit)
    register_journey_places(app, db, Problem, body, require_member, audit)
    register_media_library(app, db, Problem, body, require_member, audit)
    register_media_playback(app)
    register_inventory(app, db, Problem)
    register_calendar_publish(app, db, Problem, body, require_member, audit)
    register_task_publish(app, db, Problem, body, require_member, audit)
    register_sync_health(app, db, require_member)
    register_finance_hub(app, db, Problem, body, require_member, audit)
    register_shopping_settlement(app, db, Problem, body, require_member, audit)
    register_routines(app, db, Problem, body, require_member, audit)
    register_assistant(app, db, Problem, body, require_member, audit, limited, validate, now)
    register_portability(app, db, Problem, body, require_member, audit, limited)
    register_spaces(app, db, Problem, body, require_member, limited, create_app)
    return app


def calendar_view(value):
    if value not in ('today', 'week', 'around'):
        raise Problem('请选择今日、本周或前后 3 天')
    return value


def text_field(value, label, limit=120, allow_empty=False):
    if not isinstance(value, str):
        raise Problem(label+"格式不正确")
    value = value.strip()
    if len(value) > limit or (not value and not allow_empty):
        raise Problem(f"{label}请填写 1～{limit} 个字符" if not allow_empty else label+"过长")
    return value


def amount(value, label, maximum=100_000_000_000):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise Problem(label+"必须是有效的非负金额")
    return value


def check_owner(owner, db):
    if not isinstance(owner, str) or owner not in {"shared", "member1", "member2"}:
        raise Problem("负责人不正确")


def date_field(value, label, optional=False, timestamp=False):
    if optional and not value:
        return ""
    value = text_field(value, label, 40)
    try:
        if timestamp:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return (parsed.replace(tzinfo=TZ) if parsed.tzinfo is None else parsed.astimezone(TZ)).isoformat(timespec="seconds")
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise Problem(label+"格式不正确")


def validate(kind, value, db):
    result = {"title": text_field(value.get("title"), "名称", 100)}
    # Keep workflow linkage when a linked item is edited in an ordinary form.
    for key in ('journeyId', 'tripId'):
        link = value.get(key)
        if link:
            if not isinstance(link, str) or len(link) > 100:
                raise Problem('计划关联格式不正确')
            if key == 'tripId' and not db().execute("SELECT 1 FROM entities WHERE id=? AND kind='trips'", (link,)).fetchone():
                raise Problem('关联旅行不存在')
            result[key] = link
    if kind in {"tasks", "shopping"}:
        if not isinstance(value.get("done", False), bool):
            raise Problem("完成状态不正确")
        result["done"] = value.get("done", False)
        result["owner"] = value.get("owner", "shared")
        check_owner(result["owner"], db)
        result["note"] = text_field(value.get("note", ""), "备注", 500, True)
        if kind == "shopping":
            result["quantity"] = text_field(value.get("quantity", "1 件"), "数量", 30)
            for key, label in [('budget', '采购预算'), ('actual', '实际花费')]:
                result[key] = None if value.get(key) is None else amount(value[key], label)
            result['photoIds'] = validate_photo_ids(value.get('photoIds', []), Problem)
        else:
            result["due"] = date_field(value.get("due", ""), "截止日期", True)
            trip_id = value.get("tripId", "")
            if not isinstance(trip_id, str) or (trip_id and not db().execute("SELECT 1 FROM entities WHERE id=? AND kind='trips'", (trip_id,)).fetchone()):
                raise Problem("关联旅行不存在")
            result["tripId"] = trip_id
    elif kind == "events":
        result.update(owner=value.get("owner", "shared"), location=text_field(value.get("location", ""), "地点", 200, True),
                      note=text_field(value.get('note', ''), '日程备注', 8000, True),
                      start=date_field(value.get("start"), "开始时间", timestamp=True),
                      end=date_field(value.get("end"), "结束时间", timestamp=True),
                      allDay=bool(value.get("allDay", False)), source=text_field(value.get("source", "手动"), "来源", 30),
                      imported=bool(value.get("imported", False)))
        check_owner(result["owner"], db)
        if result["end"] < result["start"]:
            raise Problem("结束时间不能早于开始时间")
        if result["allDay"]:
            begin = datetime.fromisoformat(result["start"]).replace(hour=0, minute=0, second=0)
            end = datetime.fromisoformat(result["end"]).replace(hour=0, minute=0, second=0)
            if end <= begin:
                end = begin + timedelta(days=1)
            result.update(start=begin.isoformat(timespec="seconds"), end=end.isoformat(timespec="seconds"))
    elif kind == "trips":
        result.update(destination=text_field(value.get("destination", ""), "目的地", 80, True),
                      start=date_field(value.get("start"), "出发日期"), end=date_field(value.get("end"), "返程日期"),
                      budget=amount(value.get("budget", 0), "旅行预算"), saved=amount(value.get("saved", 0), "已预留金额"),
                      paid=amount(value.get("paid", 0), "已付款"), note=text_field(value.get("note", ""), "行程备注", 2000, True))
        if result["end"] < result["start"]:
            raise Problem("返程日期不能早于出发日期")
    return result
