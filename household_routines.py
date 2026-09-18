"""Shared, explicitly confirmed routines; local entities only, no cloud writes."""
from __future__ import annotations

import calendar
import hashlib
import json
import re
import secrets
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import g, jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

PREFIX = "/api/routines"
PREVIEW_SECONDS = 600
PAGE_SIZE = 40
MAX_PLANS = 100
MAX_ITEMS = 2500
TIME_ZONE = "Asia/Shanghai"
MAX_DATE = date(2100, 12, 31)
OPERATIONS = {"create", "update", "pause", "resume", "skip", "archive"}
ENTITY_FIELDS = {"title", "owner", "note", "done", "due", "quantity", "budget", "actual", "photoIds"}


def today():
    """One household date boundary; tests replace only this clock."""
    return datetime.now(ZoneInfo(TIME_ZONE)).date()


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def pack(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(pack(value).encode("utf-8")).hexdigest()


def next_dates(schedule, boundary, count=3, *, strict=False):
    """Anchor-based arithmetic, without walking historical occurrences.

    Monthly dates always clamp the original anchor day, never a prior clamp.
    Dates beyond the supported 2000--2100 calendar are visibly exhausted.
    """
    anchor = date.fromisoformat(schedule["anchor"])
    if strict:
        if boundary >= MAX_DATE:
            return []
        boundary += timedelta(days=1)
    frequency, interval = schedule["frequency"], schedule["interval"]
    result = []
    if frequency != "monthly":
        days = interval * (7 if frequency == "weekly" else 1)
        delta = max(0, (boundary - anchor).days)
        index = (delta + days - 1) // days
        for step in range(index, index + count):
            ordinal = anchor.toordinal() + step * days
            if ordinal > MAX_DATE.toordinal():
                break
            result.append(date.fromordinal(ordinal).isoformat())
    else:
        origin = anchor.year * 12 + anchor.month - 1
        month_delta = (boundary.year - anchor.year) * 12 + boundary.month - anchor.month
        index = max(0, month_delta // interval)
        while len(result) < count:
            year, month = divmod(origin + index * interval, 12)
            if year > MAX_DATE.year:
                break
            month += 1
            value = date(year, month, min(anchor.day, calendar.monthrange(year, month)[1]))
            if value >= boundary:
                result.append(value.isoformat())
            index += 1
    return result


def business_plan(row):
    template = json.loads(row["template"])
    schedule = json.loads(row["schedule"])
    return {"id": row["id"], "kind": row["kind"],
            "template": {key: value for key, value in template.items()
                         if key in {"title", "owner", "note", "quantity", "budget"}},
            "schedule": {key: value for key, value in schedule.items()
                         if key in {"frequency", "interval", "anchor", "timeZone", "monthEnd"}},
            "state": row["state"], "revision": row["revision"], "currentIndex": row["current_index"],
            "createdBy": row["created_by"], "createdAt": row["created_at"], "updatedAt": row["updated_at"]}


def export_shared_routines(con):
    """Only explicit includeShared callers use this; no authentication material."""
    plans = [business_plan(row) for row in con.execute("SELECT * FROM household_routines ORDER BY id")]
    occurrences = [{"planId": row["plan_id"], "index": row["occurrence_index"], "entityId": row["entity_id"],
                    "scheduledOn": row["scheduled_on"], "state": row["state"],
                    "createdAt": row["created_at"], "closedAt": row["closed_at"]}
                   for row in con.execute("SELECT * FROM routine_occurrences ORDER BY plan_id,occurrence_index")]
    receipts = []
    for row in con.execute("SELECT id,operation,plan_id,result,created_at FROM routine_receipts ORDER BY id"):
        saved = json.loads(row["result"])
        generated = saved.get("generated")
        receipts.append({"id": row["id"], "operation": row["operation"], "planId": row["plan_id"],
                         "createdAt": row["created_at"],
                         "generatedId": generated.get("id") if isinstance(generated, dict) else None})
    return {"plans": plans, "occurrences": occurrences, "receipts": receipts}


class RoutineEngine:
    def __init__(self, app, db, Problem):
        self.app, self.db, self.Problem = app, db, Problem

    def row(self, con, plan_id):
        row = con.execute("SELECT * FROM household_routines WHERE id=?", (plan_id,)).fetchone()
        if row is None:
            raise self.Problem("例行计划不存在", 404)
        return dict(row)

    def current(self, con, rule):
        occurrence = con.execute("SELECT * FROM routine_occurrences WHERE plan_id=? AND occurrence_index=?",
                                 (rule["id"], rule["current_index"])).fetchone()
        if occurrence is None:
            return None, None
        entity = con.execute("SELECT * FROM entities WHERE id=? AND kind=?",
                             (occurrence["entity_id"], rule["kind"])).fetchone()
        return dict(occurrence), dict(entity) if entity else None

    @staticmethod
    def counts(con):
        items = {"tasks": 0, "shopping": 0}
        items.update({row[0]: row[1] for row in con.execute(
            "SELECT kind,count(*) FROM entities WHERE kind IN ('tasks','shopping') GROUP BY kind")})
        return {"activePlans": con.execute("SELECT count(*) FROM household_routines WHERE state!='archived'").fetchone()[0],
                "items": items}

    @staticmethod
    def dates(rule, current, day):
        anchor = max(day, date.fromisoformat(current["scheduled_on"])) if current else day
        return next_dates(json.loads(rule["schedule"]), anchor, strict=bool(current))

    def occurrence(self, con, rule, row, *, current=False):
        entity = con.execute("SELECT id,kind,data,revision FROM entities WHERE id=? AND kind=?",
                             (row["entity_id"], rule["kind"])).fetchone()
        value = json.loads(entity["data"]) if entity else None
        state = row["state"]
        if state == "current":
            state = "missing" if value is None else "completed" if value.get("done") is True else "pending"
        return {"index": row["occurrence_index"], "scheduledOn": row["scheduled_on"],
                "entityId": row["entity_id"], "state": state,
                "entity": None if value is None else
                    {**{k: v for k, v in value.items() if k in ENTITY_FIELDS},
                     "id": entity["id"], "revision": entity["revision"]}}

    def public(self, con, rule, day, counts=None):
        counts = counts or self.counts(con)
        current, entity = self.current(con, rule)
        dates = self.dates(rule, current, day)
        status = rule["state"]
        if status == "active":
            status = "missing" if not entity else "completed" if json.loads(entity["data"]).get("done") is True else "pending"
            if status == "completed":
                if not dates:
                    status = "exhausted"
                elif counts["items"][rule["kind"]] >= MAX_ITEMS:
                    status = "capacity_blocked"
        output = business_plan(rule)
        output.pop("currentIndex")
        output.update(status=status, current=self.occurrence(con, rule, current, current=True) if current else None,
                      nextDates=dates,
                      history=[self.occurrence(con, rule, dict(row)) for row in con.execute(
                          "SELECT * FROM routine_occurrences WHERE plan_id=? ORDER BY occurrence_index DESC LIMIT 10",
                          (rule["id"],))])
        return output

    @staticmethod
    def materialize(rule, due):
        value = json.loads(rule["template"])
        value = {**value, "done": False}
        if rule["kind"] == "shopping":
            value.update(actual=None, photoIds=[])
        else:
            value.update(due=due, tripId="")
        return value

    def generate(self, con, rule, due, *, close_state="completed"):
        current, _ = self.current(con, rule)
        if self.counts(con)["items"][rule["kind"]] >= MAX_ITEMS:
            raise self.Problem("该类事项已达 2500 条，请先整理；计划和当前事项保持不变", 409)
        moment, entity_id = stamp(), secrets.token_hex(12)
        index = rule["current_index"] + 1
        if current:
            con.execute("UPDATE routine_occurrences SET state=?,closed_at=? "
                        "WHERE plan_id=? AND occurrence_index=? AND state='current'",
                        (close_state, moment, rule["id"], current["occurrence_index"]))
        con.execute("INSERT INTO entities(id,kind,data,updated_at) VALUES(?,?,?,?)",
                    (entity_id, rule["kind"], pack(self.materialize(rule, due)), moment))
        con.execute("INSERT INTO routine_occurrences(plan_id,occurrence_index,entity_id,scheduled_on,state,created_at) "
                    "VALUES(?,?,?,?,'current',?)", (rule["id"], index, entity_id, due, moment))
        con.execute("UPDATE household_routines SET current_index=?,revision=revision+1,updated_at=? WHERE id=?",
                    (index, moment, rule["id"]))
        return {"id": entity_id, "kind": rule["kind"], "revision": 1, "scheduledOn": due}

    def tick(self):
        """Run independently of request actors. At most one successor per rule."""
        result = {"examined": 0, "generated": 0, "missing": 0, "blocked": 0}
        with self.app.app_context():
            con = self.db()
            ids = [row[0] for row in con.execute("SELECT id FROM household_routines WHERE state='active' ORDER BY id")]
            for plan_id in ids:
                # A read-only hint avoids contending for a write lock on every
                # idle rule. It never authorizes a write: recheck after BEGIN.
                hint = self.row(con, plan_id)
                if hint['state'] != 'active':
                    continue
                result['examined'] += 1
                current_hint, entity_hint = self.current(con, hint)
                if not current_hint or not entity_hint:
                    result['missing'] += 1
                    continue
                if json.loads(entity_hint['data']).get('done') is not True:
                    continue
                if not self.dates(hint, current_hint, today()) or self.counts(con)['items'][hint['kind']] >= MAX_ITEMS:
                    result['blocked'] += 1
                    continue
                try:
                    con.execute("BEGIN IMMEDIATE")
                    rule = self.row(con, plan_id)
                    if rule["state"] != "active":
                        con.rollback()
                        continue
                    current, entity = self.current(con, rule)
                    if not current or not entity:
                        result["missing"] += 1
                        con.rollback()
                        continue
                    if json.loads(entity["data"]).get("done") is not True:
                        con.rollback()
                        continue
                    dates = self.dates(rule, current, today())
                    if not dates or self.counts(con)["items"][rule["kind"]] >= MAX_ITEMS:
                        result["blocked"] += 1
                        con.rollback()
                        continue
                    self.generate(con, rule, dates[0])
                    con.execute("INSERT INTO audit(actor,action,target,stamp) VALUES('system:routines',?,?,?)",
                                ("routines.advance", plan_id, stamp()))
                    con.execute("UPDATE settings SET revision=revision+1 WHERE id='meta'")
                    con.commit()
                    result["generated"] += 1
                except BaseException:
                    con.rollback()
                    raise
        return result

    def brief(self, con):
        """Shared assistant hints, using this caller's existing read transaction."""
        day, counts = today(), self.counts(con)
        horizon = min(MAX_DATE.toordinal(), day.toordinal() + 7)
        items, due_count, issue_count = [], 0, 0
        issues = {"missing", "capacity_blocked", "exhausted"}
        for raw in con.execute("SELECT * FROM household_routines WHERE state='active' ORDER BY id"):
            rule = self.public(con, dict(raw), day, counts)
            current, status = rule["current"], rule["status"]
            scheduled = current["scheduledOn"] if current else None
            is_due = status in {"pending", "missing"} and scheduled and scheduled <= day.isoformat()
            due_count += int(bool(is_due))
            issue_count += int(status in issues)
            within_week = scheduled and date.fromisoformat(scheduled).toordinal() <= horizon
            if status in issues or (status == "pending" and within_week):
                items.append({"id": rule["id"], "title": rule["template"]["title"], "kind": rule["kind"],
                              "owner": rule["template"]["owner"], "scheduledOn": scheduled, "status": status})
        items.sort(key=lambda item: (item["status"] not in issues, item["scheduledOn"] or "", item["id"]))
        return {"items": items[:8], "dueCount": due_count, "issueCount": issue_count, "limit": 8}


def register_routines(app, db, Problem, body, require_member, audit):
    with app.app_context():
        db().executescript("""
        CREATE TABLE IF NOT EXISTS household_routines(
            id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('tasks','shopping')),
            template TEXT NOT NULL, schedule TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('active','paused','archived')),
            revision INTEGER NOT NULL DEFAULT 1, current_index INTEGER NOT NULL DEFAULT 0,
            created_by TEXT NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS household_routines_state ON household_routines(state,id);
        CREATE TABLE IF NOT EXISTS routine_occurrences(
            plan_id TEXT NOT NULL REFERENCES household_routines(id),
            occurrence_index INTEGER NOT NULL CHECK(occurrence_index>0), entity_id TEXT NOT NULL UNIQUE,
            scheduled_on TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('current','completed','skipped')),
            created_at TEXT NOT NULL, closed_at TEXT,
            PRIMARY KEY(plan_id,occurrence_index));
        CREATE UNIQUE INDEX IF NOT EXISTS routine_occurrences_current
            ON routine_occurrences(plan_id) WHERE state='current';
        CREATE TABLE IF NOT EXISTS routine_receipts(
            id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), nonce_digest TEXT NOT NULL,
            operation TEXT NOT NULL, plan_id TEXT NOT NULL REFERENCES household_routines(id),
            result TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(owner,nonce_digest));
        """)
        db().commit()
    engine = RoutineEngine(app, db, Problem)
    app.extensions["household_routines"] = engine
    signer = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="household-routines-preview-v1")

    def authenticated(con):
        require_member()
        sessions = app.extensions.get("member_sessions")
        if sessions is None:
            raise Problem("暂时无法核对登录状态，请稍后重试", 503)
        current = sessions.current(con)
        original = getattr(g, "member_session", {})
        household = app.config.get("HOUSEHOLD_INFO", {}).get("id", "default")
        if (current["owner"] != g.actor["id"] or current["auth_version"] != g.actor.get("auth_version")
                or current["id"] != original.get("id")
                or household != g.actor.get("householdId")):
            raise Problem("登录或家庭已变化，请重新打开", 401)
        return current["owner"], digest({"household": household, "owner": current["owner"],
            "session": current["id"], "credential": current["credential_hash"], "authVersion": current["auth_version"]})

    @contextmanager
    def transaction(*, write=False):
        con = db()
        try:
            con.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            owner, context = authenticated(con)
            yield con, owner, context
            if write:
                # Revocation cannot acquire this writer lock; expiry and the
                # captured session must still be checked after business/audit.
                authenticated(con)
                con.commit()
            else:
                # Observe revocation committed while this read snapshot lived.
                con.rollback()
                authenticated(con)
                # Legacy-cookie resolution may open an implicit UPDATE.
                con.rollback()
        except BaseException:
            con.rollback()
            raise

    def identifier(value):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
            raise Problem("计划编号格式不正确")
        return value

    def integer(value, label, low, high):
        if type(value) is not int or not low <= value <= high:
            raise Problem(label + "须为范围内整数")
        return value

    def fields(value, allowed, required):
        if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
            raise Problem("字段不完整或包含不支持的字段")

    def text(value, label, limit, *, empty=False):
        if not isinstance(value, str) or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", value):
            raise Problem(label + "格式不正确")
        value = value.strip()
        if len(value) > limit or (not empty and not value):
            raise Problem(label + "长度不正确")
        return value

    def template(value, kind, con):
        keys = {"title", "owner", "note"} | ({"quantity", "budget"} if kind == "shopping" else set())
        fields(value, keys, keys)
        owner = value["owner"]
        if not isinstance(owner, str) or (owner != "shared" and not con.execute("SELECT 1 FROM household_memberships WHERE member_id=? AND state='active'", (owner,)).fetchone()):
            raise Problem("请选择本家庭负责人")
        output = {"title": text(value["title"], "名称", 100), "owner": owner,
                  "note": text(value["note"], "备注", 500, empty=True)}
        if kind == "shopping":
            output["quantity"] = text(value["quantity"], "数量", 30)
            output["budget"] = None if value["budget"] is None else integer(value["budget"], "预算", 0, 100_000_000_000)
        return output

    def schedule(value):
        fields(value, {"frequency", "interval", "anchor", "timeZone", "monthEnd"}, {"frequency", "interval", "anchor"})
        frequency = value["frequency"]
        if not isinstance(frequency, str) or frequency not in {"daily", "weekly", "monthly"}:
            raise Problem("请选择每日、每周或每月")
        interval = integer(value["interval"], "间隔", 1, {"daily": 365, "weekly": 52, "monthly": 12}[frequency])
        anchor = value["anchor"]
        try:
            if not isinstance(anchor, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", anchor):
                raise ValueError()
            parsed = date.fromisoformat(anchor)
            if not 2000 <= parsed.year <= 2100:
                raise ValueError()
        except ValueError:
            raise Problem("锚点须为 2000—2100 年内的有效 YYYY-MM-DD 日期") from None
        if value.get("timeZone", TIME_ZONE) != TIME_ZONE or value.get("monthEnd", "clamp") != "clamp":
            raise Problem("本版固定按上海日期计算，短月取当月最后一天")
        return {"frequency": frequency, "interval": interval, "anchor": anchor, "timeZone": TIME_ZONE, "monthEnd": "clamp"}

    def normalize(value, con):
        operation = value.get("operation")
        if not isinstance(operation, str) or operation not in OPERATIONS:
            raise Problem("操作不正确")
        keys = {"operation", "kind", "template", "schedule"} if operation == "create" else {"operation", "planId", "revision"}
        if operation == "update":
            keys |= {"template", "schedule"}
        fields(value, keys, keys)
        output = dict(value)
        if operation != "create":
            output["planId"] = identifier(value["planId"])
            output["revision"] = integer(value["revision"], "计划版本", 1, 2**63 - 1)
            kind = engine.row(con, value["planId"])["kind"]
        else:
            kind = value["kind"]
            if not isinstance(kind, str) or kind not in {"tasks", "shopping"}:
                raise Problem("请选择待办或采购")
        if operation in {"create", "update"}:
            output["template"] = template(value["template"], kind, con)
            output["schedule"] = schedule(value["schedule"])
        return output

    def assess(con, value, day):
        operation = value["operation"]
        rule = None if operation == "create" else engine.row(con, value["planId"])
        counts = engine.counts(con)
        current, entity = (None, None) if rule is None else engine.current(con, rule)
        before = None if rule is None else engine.public(con, rule, day, counts)
        if rule:
            if rule["revision"] != value["revision"]:
                raise Problem("计划已修改，请保留草稿并重新预览", 409)
            if rule["state"] == "archived":
                raise Problem("计划已归档，只能查看历史", 409)
            if operation == "pause" and rule["state"] != "active":
                raise Problem("只有运行中的计划可以暂停", 409)
            if operation == "resume" and rule["state"] != "paused":
                raise Problem("只有暂停的计划可以恢复", 409)
            if operation == "skip" and rule["state"] != "active":
                raise Problem("请先恢复计划，再明确跳过本期", 409)
        elif counts["activePlans"] >= MAX_PLANS:
            raise Problem("未归档计划已达 100 个，请先归档不再使用的计划", 409)
        after = {"kind": value["kind"] if rule is None else rule["kind"],
                 "template": value["template"] if operation in {"create", "update"} else json.loads(rule["template"]),
                 "schedule": value["schedule"] if operation in {"create", "update"} else json.loads(rule["schedule"]),
                 "state": "active" if rule is None or operation == "resume" else
                          "paused" if operation == "pause" else "archived" if operation == "archive" else rule["state"]}
        candidate = {**after, "template": pack(after["template"]), "schedule": pack(after["schedule"])}
        dates = engine.dates(candidate, current, day)
        should_generate = operation in {"create", "skip"} or (
            operation == "resume" and entity is not None and json.loads(entity["data"]).get("done") is True)
        if operation == "skip" and current is None:
            raise Problem("当前期记录缺失，请联系维护者核对，不会自动重建", 409)
        if should_generate and (not dates or counts["items"][after["kind"]] >= MAX_ITEMS):
            raise Problem("下一期日期或事项容量不可用，当前规则和事项保持不变", 409)
        will_generate = None if not should_generate else {
            "index": 1 if rule is None else rule["current_index"] + 1, "scheduledOn": dates[0],
            "kind": after["kind"], "data": engine.materialize(candidate, dates[0])}
        warnings = ["此计划及模板对本家庭成员共享，请勿填写私人账户、财务明细或登录凭据。",
                    "只生成本地事项，不自动发布到 Microsoft 或 Google。"]
        if after["schedule"]["frequency"] == "monthly":
            warnings.append("每期从原锚点的日计算；例如 31 日遇短月取当月月底，下个月仍按 31 日。")
        if operation == "skip":
            warnings.append("跳过本期并保留现有事项；不会删除、修改或标为完成，历史固定记录为已跳过。")
        elif operation == "update":
            warnings.append("规则修改只影响未来；当前事项的标题、日期、金额、完成状态和图片保持不变。")
        elif operation in {"pause", "archive"}:
            warnings.append("停止后续自动生成；现有事项保持原样，不删除也不取消云端事项。")
        if rule and (not current or not entity):
            warnings.append("当前事项已缺失，不会自动复活；运行中可明确跳过本期。")
        dependencies = digest({"rule": rule, "current": current, "entity": entity, "today": day.isoformat(), "capacity": counts})
        return dependencies, {"operation": operation, "today": day.isoformat(), "timeZone": TIME_ZONE,
                              "before": before, "after": after, "nextDates": dates,
                              "willGenerate": will_generate, "warnings": warnings}

    @app.get(PREFIX + "/context")
    def routine_context():
        require_member()
        if set(request.args) - {"planId", "page", "includeArchived"} or any(len(request.args.getlist(k)) != 1 for k in request.args):
            raise Problem("查询参数不正确")
        page = request.args.get("page", "0")
        if not re.fullmatch(r"0|[1-9]\d{0,8}", page):
            raise Problem("页码格式不正确")
        page = int(page)
        include = request.args.get("includeArchived", "false")
        if include not in {"true", "false"}:
            raise Problem("归档筛选须为 true 或 false")
        plan_id = identifier(request.args["planId"]) if "planId" in request.args else None
        with transaction() as (con, _, _):
            where = "" if include == "true" else "WHERE state!='archived'"
            rows = [dict(row) for row in con.execute(
                "SELECT * FROM household_routines " + where + " ORDER BY created_at DESC,id LIMIT ? OFFSET ?",
                (PAGE_SIZE + 1, page * PAGE_SIZE))]
            more, rows = len(rows) > PAGE_SIZE, rows[:PAGE_SIZE]
            if plan_id and plan_id not in {row["id"] for row in rows}:
                rows.append(engine.row(con, plan_id))
            day, counts = today(), engine.counts(con)
            result = {"version": 1, "today": day.isoformat(), "timeZone": TIME_ZONE,
                      "limit": {"activePlans": MAX_PLANS, "itemsPerKind": MAX_ITEMS},
                      "plans": [engine.public(con, row, day, counts) for row in rows],
                      "pageInfo": {"page": page, "pageSize": PAGE_SIZE, "more": more}}
            return jsonify(result)

    @app.post(PREFIX + "/preview")
    def routine_preview():
        require_member()
        with transaction() as (con, owner, context):
            value = normalize(body(), con)
            dependencies, output = assess(con, value, today())
            nonce = secrets.token_hex(24)
            token = signer.dumps({"version": 1, "owner": owner, "context": context, "nonce": nonce,
                                  "request": value, "dependencies": dependencies})
            return jsonify(**output, previewToken=token, operationKey=digest(nonce), expiresInSeconds=PREVIEW_SECONDS)

    @app.get(PREFIX + "/operations/<operation_key>")
    def routine_operation(operation_key):
        require_member()
        if not re.fullmatch(r"[a-f0-9]{64}", operation_key) or request.args:
            raise Problem("操作编号或查询参数格式不正确")
        with transaction() as (con, owner, _):
            row = con.execute("SELECT operation,plan_id,result,created_at FROM routine_receipts "
                              "WHERE owner=? AND nonce_digest=?", (owner, operation_key)).fetchone()
            if row is None:
                response = jsonify(error="尚未找到此操作的回执；原请求仍可能在处理中",
                                   code="routine_receipt_not_found")
                response.status_code = 404
            else:
                saved = json.loads(row["result"])
                generated = saved["generated"]
                response = jsonify(found=True, operationKey=operation_key, operation=row["operation"],
                                   planId=row["plan_id"], revision=saved["plan"]["revision"],
                                   generated=None if generated is None else
                                   {key: generated[key] for key in ("id", "kind", "revision", "scheduledOn")},
                                   createdAt=row["created_at"])
            response.headers["Cache-Control"] = "no-store"
            return response

    @app.post(PREFIX + "/confirm")
    def routine_confirm():
        require_member()
        payload = body()
        fields(payload, {"previewToken"}, {"previewToken"})
        token = payload["previewToken"]
        if not isinstance(token, str) or not 1 <= len(token) <= 12000:
            raise Problem("预览凭据格式不正确")
        try:
            # Authenticate the envelope now, but decide expiry only after the
            # writer lock and receipt lookup. A lost response can outlive TTL.
            signed = signer.loads(token)
        except BadSignature:
            raise Problem("预览凭据无法核对，请保留草稿", 400) from None
        if (not isinstance(signed, dict) or signed.get("version") != 1
                or not isinstance(signed.get("nonce"), str) or not re.fullmatch(r"[a-f0-9]{48}", signed["nonce"])):
            raise Problem("预览凭据格式不正确")
        with transaction(write=True) as (con, owner, context):
            if signed.get("owner") != owner or signed.get("context") != context:
                raise Problem("预览属于其他成员、家庭或会话，请重新预览", 403)
            nonce = digest(signed["nonce"])
            previous = con.execute("SELECT result FROM routine_receipts WHERE owner=? AND nonce_digest=?", (owner, nonce)).fetchone()
            if previous:
                return jsonify(**{**json.loads(previous["result"]), "operationKey": nonce, "replayed": True})
            try:
                signer.loads(token, max_age=PREVIEW_SECONDS)
            except SignatureExpired:
                # Other confirms serialize on this lock and check expiry here
                # too. A missing GET alone cannot establish this outcome.
                return jsonify(error="原预览已过期，且核实尚未执行；请保留草稿重新预览",
                               code="preview_expired_unapplied"), 410
            day = today()
            try:
                value = normalize(signed["request"], con)
                dependencies, output = assess(con, value, day)
            except Problem as exc:
                if exc.status in {400, 404}:
                    raise Problem("计划或依赖已变化，请保留草稿并重新预览", 409) from None
                raise
            if dependencies != signed["dependencies"]:
                raise Problem("日期、计划、当前事项或容量已变化，请保留草稿并重新预览", 409)
            operation, moment = value["operation"], stamp()
            if operation == "create":
                plan_id = secrets.token_hex(16)
                con.execute("INSERT INTO household_routines(id,kind,template,schedule,state,created_by,created_at,updated_at) "
                            "VALUES(?,?,?,?,'active',?,?,?)",
                            (plan_id, value["kind"], pack(value["template"]), pack(value["schedule"]), owner, moment, moment))
            else:
                plan_id = value["planId"]
                con.execute("UPDATE household_routines SET template=?,schedule=?,state=?,revision=revision+1,updated_at=? WHERE id=?",
                            (pack(output["after"]["template"]), pack(output["after"]["schedule"]), output["after"]["state"], moment, plan_id))
            generated = None
            if output["willGenerate"]:
                generated = engine.generate(con, engine.row(con, plan_id), output["willGenerate"]["scheduledOn"],
                                            close_state="skipped" if operation == "skip" else "completed")
            result = {"operation": operation, "plan": engine.public(con, engine.row(con, plan_id), day),
                      "generated": generated, "replayed": False}
            con.execute("INSERT INTO routine_receipts VALUES(?,?,?,?,?,?,?)",
                        (secrets.token_hex(16), owner, nonce, operation, plan_id, pack(result), moment))
            audit("routines." + operation, plan_id)
            return jsonify(**result, operationKey=nonce)
    return engine
