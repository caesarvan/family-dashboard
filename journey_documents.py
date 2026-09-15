"""Member-owned travel documents; BLOBs never enter plans, state or cloud payloads."""
from contextlib import contextmanager
from datetime import datetime, timezone
from io import BytesIO
from pathlib import PurePosixPath
from threading import BoundedSemaphore
import base64
import binascii
import hashlib
import json
import re
import secrets
import unicodedata
import warnings

from flask import g, jsonify, request, send_file
from PIL import Image, ImageOps, UnidentifiedImageError


MAX_FILE_BYTES = 5_000_000
MAX_STORED_IMAGE_BYTES = 2_000_000
MAX_TOTAL_BYTES = 200_000_000
MAX_DOCUMENTS = 500
MAX_JOURNEY_DOCUMENTS = 100
FORMATS = ['pdf', 'jpg', 'jpeg', 'png', 'webp']
DECODE_SLOT = BoundedSemaphore(1)
META_COLUMNS = ('id,journey_id,owner,title,filename,mime_type,bytes,visibility,'
                'segment_key,created_at,updated_at,revision')
SCHEMA_SQL = '''
CREATE TABLE IF NOT EXISTS journey_documents(
    id TEXT PRIMARY KEY,
    journey_id TEXT REFERENCES journey_workflows(id) ON DELETE SET NULL,
    owner TEXT NOT NULL REFERENCES users(id),
    request_id TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    title TEXT NOT NULL,
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    content BLOB NOT NULL,
    bytes INTEGER NOT NULL CHECK(bytes>=0 AND bytes=length(content)),
    visibility TEXT NOT NULL CHECK(visibility IN ('private','shared')),
    segment_key TEXT NOT NULL DEFAULT '',
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>=1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    UNIQUE(owner,request_id)
);
CREATE INDEX IF NOT EXISTS journey_documents_owner
    ON journey_documents(owner,updated_at) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS journey_documents_journey
    ON journey_documents(journey_id,visibility) WHERE deleted_at IS NULL;
CREATE TRIGGER IF NOT EXISTS journey_documents_unlinked_revision
AFTER UPDATE OF journey_id ON journey_documents
WHEN OLD.journey_id IS NOT NULL AND NEW.journey_id IS NULL
     AND NEW.revision=OLD.revision AND NEW.deleted_at IS NULL
BEGIN
    UPDATE journey_documents SET revision=revision+1,
        updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=NEW.id;
END;
'''


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def metadata(row, segments=None):
    """Business fields only; an unlinked row is private regardless of stored scope."""
    unlinked = row['journey_id'] is None
    result = {'id': row['id'], 'journeyId': row['journey_id'], 'owner': row['owner'],
              'title': row['title'], 'filename': row['filename'], 'mimeType': row['mime_type'],
              'bytes': row['bytes'], 'visibility': 'private' if unlinked else row['visibility'],
              'segmentKey': row['segment_key'], 'unlinked': unlinked,
              'createdAt': row['created_at'], 'updatedAt': row['updated_at'], 'revision': row['revision']}
    if segments is not None:
        result['segmentMissing'] = bool(row['segment_key'] and row['segment_key'] not in segments)
    return result


def exported_documents(con, owner, include_shared=False):
    """No initialization, BLOB, download URL, request key or authentication data."""
    result = {'personal': [], 'shared': []}
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='journey_documents'").fetchone():
        return result
    result['personal'] = [metadata(row) for row in con.execute(
        f'SELECT {META_COLUMNS} FROM journey_documents WHERE owner=? AND deleted_at IS NULL ORDER BY id', (owner,))]
    if include_shared:
        result['shared'] = [metadata(row) for row in con.execute(
            f'SELECT {META_COLUMNS} FROM journey_documents WHERE owner<>? AND visibility=\'shared\' '
            'AND deleted_at IS NULL AND journey_id IN (SELECT id FROM journey_workflows) ORDER BY id', (owner,))]
    return result


def register_journey_documents(app, db, Problem, body, require_member, limited, audit):
    with app.app_context():
        con = db()
        try:
            con.executescript('BEGIN IMMEDIATE;\n' + SCHEMA_SQL + '\nCOMMIT;')
        except Exception:
            con.rollback()
            raise

    def authenticated(con):
        require_member()
        engine = app.extensions.get('member_sessions')
        if engine is None:
            raise Problem('暂时无法核对登录状态，请稍后重试', 503)
        live = engine.current(con)
        household = app.config.get('HOUSEHOLD_INFO', {}).get('id', 'default')
        if (live['owner'] != g.actor['id'] or live['auth_version'] != g.actor.get('auth_version')
                or household != g.actor.get('householdId')):
            raise Problem('登录或家庭已变化，请重新打开', 401)
        return live['owner']

    @contextmanager
    def transaction(write=False):
        con = db()
        try:
            con.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            owner = authenticated(con)
            yield con, owner
            con.commit()
        except Exception:
            con.rollback()
            raise

    def fields(value, allowed, required):
        if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
            raise Problem('资料字段不完整或包含不支持的字段')

    def text(value, label, maximum, empty=False):
        if not isinstance(value, str) or any(unicodedata.category(c).startswith('C') for c in value):
            raise Problem(label + '格式不正确')
        value = value.strip()
        if len(value) > maximum or (not value and not empty):
            raise Problem(label + '长度不正确')
        return value

    def identifier(value, nullable=False):
        if nullable and value is None:
            return None
        if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{24}', value):
            raise Problem('旅行编号不正确')
        return value

    def scope(value):
        if not isinstance(value, str) or value not in ('private', 'shared'):
            raise Problem('请选择仅本人或家庭成员共享')
        return value

    def revision(value):
        if type(value) is not int or value < 1:
            raise Problem('资料版本不正确')
        return value

    def journey(con, uid):
        row = con.execute('SELECT j.id,j.plan,j.revision,e.data FROM journey_workflows j '
                          'JOIN entities e ON e.id=j.trip_id WHERE j.id=?', (uid,)).fetchone()
        if not row:
            raise Problem('旅行不存在，可能已被删除', 404)
        plan = json.loads(row['plan'])
        return {'id': row['id'], 'title': json.loads(row['data'])['title'], 'revision': row['revision']}, [
            {'key': item['key'], 'title': item['title'], 'kind': item.get('kind', 'legacy_day')}
            for item in plan.get('segments', [])]

    def valid_segment(key, segments, previous=None, journey_id=None):
        if key and key not in {s['key'] for s in segments}:
            if not previous or key != previous['segment_key'] or journey_id != previous['journey_id']:
                raise Problem('关联的行程分段不存在，请重新选择', 409)

    def visible_row(con, uid, owner, manage=False):
        row = con.execute(f'SELECT {META_COLUMNS} FROM journey_documents WHERE id=? AND deleted_at IS NULL', (uid,)).fetchone()
        if not row or not (row['owner'] == owner or row['journey_id'] is not None and row['visibility'] == 'shared'):
            raise Problem('资料不存在或不可见', 404)
        if manage and row['owner'] != owner:
            raise Problem('只有上传者可以修改或删除资料', 403)
        return row

    def serialize(con, row, owner, known_segments=None):
        segments = known_segments
        if segments is None:
            segments = {s['key'] for s in journey(con, row['journey_id'])[1]} if row['journey_id'] else set()
        return {**metadata(row, segments), 'canManage': row['owner'] == owner,
                'downloadUrl': '/api/journey-documents/' + row['id'] + '/file'}

    def raw_file(value):
        fields(value, ('name', 'mimeType', 'dataBase64'), ('name', 'mimeType', 'dataBase64'))
        name = text(value['name'], '文件名称', 180)
        if '/' in name or '\\' in name or name in ('.', '..'):
            raise Problem('文件名称不能包含路径')
        extension = PurePosixPath(name).suffix.lower().lstrip('.')
        mime = value['mimeType']
        expected = {'pdf': 'application/pdf', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                    'png': 'image/png', 'webp': 'image/webp'}
        if extension not in expected or not isinstance(mime, str) or mime != expected[extension]:
            raise Problem('请上传格式与扩展名一致的 PDF、JPG、PNG 或 WebP')
        encoded = value['dataBase64']
        if not isinstance(encoded, str):
            raise Problem('文件编码不正确')
        if len(encoded) > ((MAX_FILE_BYTES + 2) // 3) * 4:
            raise Problem('原文件不能超过 5 MB', 413)
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise Problem('文件编码不正确')
        if not raw:
            raise Problem('文件不能为空')
        if len(raw) > MAX_FILE_BYTES:
            raise Problem('原文件不能超过 5 MB', 413)
        return name, mime, raw

    def clean_file(name, mime, raw):
        if mime == 'application/pdf':
            if not re.match(rb'%PDF-(?:1\.[0-7]|2\.0)[\r\n\t ]', raw[:12]) or not raw.rstrip(b' \t\r\n').endswith(b'%%EOF'):
                raise Problem('PDF 文件头或结束标记不正确')
            return name, mime, raw
        if not DECODE_SLOT.acquire(blocking=False):
            raise Problem('正在处理另一张图片，请稍后重试', 429)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(BytesIO(raw)) as source:
                    if source.format != {'image/jpeg': 'JPEG', 'image/png': 'PNG', 'image/webp': 'WEBP'}[mime]:
                        raise Problem('图片内容与声明格式不一致')
                    if source.width * source.height > 4_000_000 or getattr(source, 'n_frames', 1) != 1:
                        raise Problem('请使用不超过 400 万像素的单帧图片')
                    source.load()
                    picture = ImageOps.exif_transpose(source)
                    picture.thumbnail((1600, 1600))
                    clean = Image.new('RGB', picture.size, 'white')
                    rgba = picture.convert('RGBA')
                    clean.paste(rgba, mask=rgba.getchannel('A'))
                    output = BytesIO()
                    clean.save(output, format='JPEG', quality=85, optimize=True)
                    content = output.getvalue()
        except (ValueError, UnidentifiedImageError, OSError, SyntaxError,
                Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise Problem('无法读取这张图片，请使用 JPG、PNG 或 WebP')
        finally:
            DECODE_SLOT.release()
        if len(content) > MAX_STORED_IMAGE_BYTES:
            raise Problem('净化后的图片过大，请缩小后重试', 413)
        return name.rsplit('.', 1)[0] + '.jpg', 'image/jpeg', content

    @app.get('/api/journey-documents')
    def list_journey_documents():
        require_member()
        if set(request.args) - {'journeyId'} or any(len(request.args.getlist(k)) != 1 for k in request.args):
            raise Problem('不支持的资料查询条件')
        uid = identifier(request.args['journeyId']) if 'journeyId' in request.args else None
        with transaction() as (con, owner):
            info, segments = journey(con, uid) if uid else (None, [])
            conditions = 'journey_id=? AND (owner=? OR visibility=\'shared\')' if uid else 'owner=?'
            params = (uid, owner) if uid else (owner,)
            rows = con.execute(f'SELECT {META_COLUMNS} FROM journey_documents WHERE deleted_at IS NULL AND '
                               + conditions + ' ORDER BY updated_at DESC,id', params).fetchall()
            choices = [{'id': row['id'], 'title': json.loads(row['data'])['title']} for row in con.execute(
                'SELECT j.id,e.data FROM journey_workflows j JOIN entities e ON e.id=j.trip_id ORDER BY j.updated_at DESC,j.id')]
            result = {'journey': info, 'segments': segments, 'journeys': choices,
                      'documents': [serialize(con, row, owner, {s['key'] for s in segments} if uid else None) for row in rows],
                      'limits': {'maxFileBytes': MAX_FILE_BYTES, 'formats': FORMATS}}
        return jsonify(result)

    @app.post('/api/journey-documents')
    def upload_journey_document():
        require_member()
        limited('journey_document_upload', 30)
        value = body()
        fields(value, ('journeyId', 'requestId', 'title', 'visibility', 'segmentKey', 'file'),
               ('journeyId', 'requestId', 'title', 'file'))
        uid = identifier(value['journeyId'])
        key = value['requestId']
        if not isinstance(key, str) or not re.fullmatch(r'[a-f0-9]{32}', key):
            raise Problem('上传请求编号须为 32 位小写十六进制')
        title = text(value['title'], '资料标题', 120)
        visibility = scope(value.get('visibility', 'private'))
        segment = text(value.get('segmentKey', ''), '行程分段', 80, True)
        name, mime, raw = raw_file(value['file'])
        digest = hashlib.sha256(json.dumps({'journeyId': uid, 'title': title, 'visibility': visibility,
            'segmentKey': segment, 'filename': name, 'mimeType': mime, 'sha256': hashlib.sha256(raw).hexdigest()},
            ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

        def replay(con, owner):
            prior = con.execute('SELECT id,payload_digest,deleted_at FROM journey_documents WHERE owner=? AND request_id=?', (owner, key)).fetchone()
            if prior:
                if prior['payload_digest'] != digest:
                    raise Problem('该上传请求编号已用于不同内容，请重新选择文件', 409)
                if prior['deleted_at'] is not None:
                    raise Problem('这次上传的资料已删除，不能通过旧请求恢复', 409)
                return serialize(con, visible_row(con, prior['id'], owner), owner)
            return None

        with transaction() as (con, owner):
            previous = replay(con, owner)
            if previous is not None:
                return jsonify(document=previous, replayed=True), 200
            _, segments = journey(con, uid)
            valid_segment(segment, segments)
        filename, stored_mime, content = clean_file(name, mime, raw)
        with transaction(True) as (con, owner):
            previous = replay(con, owner)
            if previous is not None:
                return jsonify(document=previous, replayed=True), 200
            _, segments = journey(con, uid)
            valid_segment(segment, segments)
            count, size = con.execute('SELECT count(*),coalesce(sum(bytes),0) FROM journey_documents WHERE deleted_at IS NULL').fetchone()
            trip_count = con.execute('SELECT count(*) FROM journey_documents WHERE journey_id=? AND deleted_at IS NULL', (uid,)).fetchone()[0]
            if count >= MAX_DOCUMENTS or size + len(content) > MAX_TOTAL_BYTES or trip_count >= MAX_JOURNEY_DOCUMENTS:
                raise Problem('资料空间或数量已达上限，请整理本人不再需要的资料', 409)
            document_id, changed = secrets.token_hex(16), stamp()
            con.execute('INSERT INTO journey_documents(id,journey_id,owner,request_id,payload_digest,title,filename,mime_type,'
                        'content,bytes,visibility,segment_key,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (document_id, uid, owner, key, digest, title, filename, stored_mime, content, len(content), visibility, segment, changed, changed))
            audit('journey_document_upload', document_id)
            document = serialize(con, visible_row(con, document_id, owner), owner, {s['key'] for s in segments})
        return jsonify(document=document, replayed=False), 201

    @app.patch('/api/journey-documents/<document_id>')
    def update_journey_document(document_id):
        require_member()
        value = body()
        fields(value, ('revision', 'title', 'visibility', 'segmentKey', 'journeyId'),
               ('revision', 'title', 'visibility', 'segmentKey', 'journeyId'))
        expected = revision(value['revision'])
        title, visibility = text(value['title'], '资料标题', 120), scope(value['visibility'])
        segment, uid = text(value['segmentKey'], '行程分段', 80, True), identifier(value['journeyId'], True)
        if uid is None and (visibility != 'private' or segment):
            raise Problem('解除旅行关联时须设为仅本人并清空分段')
        with transaction(True) as (con, owner):
            row = visible_row(con, document_id, owner, True)
            if row['revision'] != expected:
                raise Problem('资料已变化，请读取最新版本再编辑', 409)
            segments = journey(con, uid)[1] if uid else []
            valid_segment(segment, segments, row, uid)
            if uid != row['journey_id'] and uid is not None:
                count = con.execute('SELECT count(*) FROM journey_documents WHERE journey_id=? AND deleted_at IS NULL', (uid,)).fetchone()[0]
                if count >= MAX_JOURNEY_DOCUMENTS:
                    raise Problem('目标旅行资料数量已达上限', 409)
            changed = con.execute('UPDATE journey_documents SET journey_id=?,title=?,visibility=?,segment_key=?,revision=revision+1,updated_at=? '
                                  'WHERE id=? AND revision=? AND deleted_at IS NULL', (uid, title, visibility, segment, stamp(), document_id, expected)).rowcount
            if changed != 1:
                raise Problem('资料已变化，请读取最新版本再编辑', 409)
            audit('journey_document_update', document_id)
            document = serialize(con, visible_row(con, document_id, owner), owner, {s['key'] for s in segments})
        return jsonify(document=document)

    @app.delete('/api/journey-documents/<document_id>')
    def delete_journey_document(document_id):
        require_member()
        value = body()
        fields(value, ('revision',), ('revision',))
        expected = revision(value['revision'])
        with transaction(True) as (con, owner):
            row = visible_row(con, document_id, owner, True)
            if row['revision'] != expected:
                raise Problem('资料已变化，请读取最新版本再删除', 409)
            changed = stamp()
            con.execute("UPDATE journey_documents SET content=?,bytes=0,title='',filename='',mime_type='',segment_key='',"
                        "journey_id=NULL,visibility='private',deleted_at=?,updated_at=?,revision=revision+1 WHERE id=? AND revision=?",
                        (b'', changed, changed, document_id, expected))
            audit('journey_document_delete', document_id)
        return jsonify(deleted=True, id=document_id)

    @app.get('/api/journey-documents/<document_id>/file')
    def download_journey_document(document_id):
        require_member()
        with transaction() as (con, owner):
            row = visible_row(con, document_id, owner)
            content = con.execute('SELECT content FROM journey_documents WHERE id=? AND deleted_at IS NULL', (document_id,)).fetchone()[0]
        response = send_file(BytesIO(bytes(content)), mimetype=row['mime_type'], as_attachment=True,
                             download_name=row['filename'], etag=False, max_age=0, conditional=False)
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "sandbox; default-src 'none'"
        return response
