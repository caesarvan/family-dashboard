"""Member-owned photo uploads. Raw originals live only during a bounded request.

The existing encrypted import/item tables remain authoritative. This source does
not impersonate a provider account or use the Google worker's session protocol.
"""
import hashlib
import re
import secrets
from threading import BoundedSemaphore

from flask import jsonify, request

from household_media import (ACTIVE, CONSENT_VERSION, ITEM_RESERVATION, MediaError,
                             _consent, _fields, _id, _key, _revision, _request_object, _clear_video_error_frames)
from media_images import FORMATS, MAX_INPUT_BYTES, MediaImageError, sanitize_media_preview

SOURCE = 'local-upload'
MAX_FILES = 10
UPLOAD_SECONDS = 60
_UPLOAD_SLOT = BoundedSemaphore(1)


def declarations(value):
    if type(value) is not list or not 1 <= len(value) <= MAX_FILES:
        raise MediaError('invalid_input')
    result, ids = [], set()
    for item in value:
        _fields(item, {'clientFileId', 'filename', 'contentType', 'bytes', 'sha256'},
                {'clientFileId', 'filename', 'contentType', 'bytes', 'sha256'})
        uid = _key(item['clientFileId'])
        name = item['filename']
        try:
            valid_name = (type(name) is str and name not in ('', '.', '..')
                          and len(name.encode('utf-8')) <= 255
                          and not any(ord(c) < 32 or ord(c) == 127 or c in '/\\' for c in name))
        except UnicodeError:
            valid_name = False
        if (uid in ids or not valid_name or type(item['contentType']) is not str or item['contentType'] not in FORMATS
                or type(item['bytes']) is not int or not 1 <= item['bytes'] <= MAX_INPUT_BYTES
                or type(item['sha256']) is not str or not re.fullmatch('[a-f0-9]{64}', item['sha256'])):
            raise MediaError('invalid_input')
        ids.add(uid)
        result.append(dict(item))
    return result


class LocalPhotoUploads:
    def __init__(self, engine):
        self.engine = engine

    def _active(self, con, uid, owner):
        row = self.engine._import(con, uid, owner)
        if self.engine._import_source(row) != SOURCE:
            raise MediaError('not_found')
        if not self.engine._context_valid(con, row):
            raise MediaError('gone')
        return row

    def detail(self, row):
        """Only the owning member's import response gets file declarations."""
        files = []
        if row['manifest_cipher']:
            for slot in self.engine._manifest(row)['slots']:
                value = {key: slot[key] for key in ('slotId', 'clientFileId', 'filename',
                         'contentType', 'bytes', 'sha256', 'status')}
                if slot.get('error_code'):
                    from household_media import ERRORS
                    code = slot['error_code']
                    value['error'] = {'code': code, 'message': ERRORS[code][1]}
                files.append(value)
        return {'files': files, 'canUpload': row['state'] == 'staging'}

    def terminal_context(self, row, value):
        if self.engine._import_source(row) != SOURCE:
            return value
        context = self.engine._open('import-context', row, row['context_cipher'])
        return {**value, 'source': SOURCE, 'version': 1,
                **{key: context[key] for key in ('finishRequestId', 'finishKey') if key in context}}

    def create(self, value):
        _fields(value, {'requestId', 'consentVersion', 'allowTemporaryProcessing', 'files'},
                {'requestId', 'consentVersion', 'allowTemporaryProcessing', 'files'})
        _consent(value, 'allowTemporaryProcessing')
        request_id, files = _key(value['requestId']), declarations(value['files'])
        context, _ = self.engine.sessions.capture(claim=False, member=True)
        with self.engine.transaction(True) as con:
            owner = self.engine._member(con)
            digest = self.engine._receipt(owner, {'source': SOURCE, **value})
            prior = con.execute('SELECT * FROM media_imports WHERE owner=? AND request_id=?',
                                (owner, request_id)).fetchone()
            if prior:
                if prior['request_key'] != digest or self.engine._import_source(prior) != SOURCE:
                    raise MediaError('conflict')
                uid, replayed = prior['id'], True
            else:
                self.engine.sessions.validate_context(con, context, member=True)
                now = self.engine.clock()
                rows = con.execute('SELECT state,created_at FROM media_imports WHERE owner=?', (owner,)).fetchall()
                if (len(rows) >= 2000 or sum(row['state'] in ACTIVE for row in rows) >= 2
                        or sum(row['created_at'] > now - 86400 for row in rows) >= 10):
                    raise MediaError('quota')
                uid, replayed = secrets.token_hex(12), False
                row = {'id': uid, 'owner': owner}
                slots = [{**item, 'slotId': secrets.token_hex(12), 'itemId': secrets.token_hex(12),
                          'status': 'pending', 'error_code': None} for item in files]
                manifest = {'source': SOURCE, 'version': 1, 'media': [], 'slots': slots}
                protected = self.engine._seal('import-context', row, {'source': SOURCE, 'version': 1,
                    'member': context, 'temporaryConsent': {'version': CONSENT_VERSION, 'at': now}})
                con.execute('''INSERT INTO media_imports
                    (id,owner,account_id,request_id,request_key,state,created_at,updated_at,expires_at,
                     context_cipher,manifest_cipher,reserved_bytes) VALUES(?,?,NULL,?,?,'staging',?,?,?,?,?,?)''',
                    (uid, owner, request_id, digest, now, now, now + 86400, protected,
                     self.engine._seal('picker-manifest', row, manifest), len(slots) * ITEM_RESERVATION))
                self.engine._quota(con, owner)
                self.engine._audit(con, owner, 'media_local_import_start', uid)
        return {**self.engine.import_detail(uid), 'replayed': replayed}

    def upload(self, uid, slot_id, revision):
        _id(uid), _id(slot_id), _revision(revision)
        # Obtain a tiny authorization snapshot before admitting the large body.
        with self.engine.transaction() as con:
            owner = self.engine._member(con)
            row = self._active(con, uid, owner)
            slot = next((s for s in self.engine._manifest(row)['slots'] if s['slotId'] == slot_id), None)
            if slot is None:
                raise MediaError('not_found')
            if request.mimetype != slot['contentType'] or request.content_length != slot['bytes']:
                raise MediaError('local_upload_mismatch')
        if not _UPLOAD_SLOT.acquire(blocking=False):
            raise MediaError('local_upload_busy')
        raw = preview = None
        lease = None
        try:
            with self.engine.transaction(True) as con:
                owner = self.engine._member(con)
                row = self._active(con, uid, owner)
                manifest = self.engine._manifest(row)
                slot = next(s for s in manifest['slots'] if s['slotId'] == slot_id)
                if slot['status'] != 'pending':
                    # Read/hash only below, so changed bytes cannot masquerade as
                    # an acknowledged earlier upload. No decoder/DB write on replay.
                    replayed = True
                else:
                    replayed = False
                    if row['state'] != 'staging' or row['revision'] != revision:
                        raise MediaError('conflict')
                    if row['lease_token'] and row['lease_until'] > self.engine.clock():
                        raise MediaError('local_upload_busy')
                    lease = secrets.token_hex(16)
                    con.execute('UPDATE media_imports SET lease_token=?,lease_until=? WHERE id=?',
                                (lease, self.engine.clock() + UPLOAD_SECONDS, uid))
            raw = request.stream.read(MAX_INPUT_BYTES + 1)
            if len(raw) != slot['bytes'] or hashlib.sha256(raw).hexdigest() != slot['sha256']:
                raise MediaError('local_upload_mismatch')
            error_code = None
            if not replayed:
                try:
                    preview = sanitize_media_preview(raw, slot['contentType'])
                except MediaImageError as error:
                    error_code = {'input_too_large': 'too_large', 'too_many_pixels': 'unsupported_image',
                                  'multiple_frames': 'unsupported_image'}.get(error.code, 'unsupported_image')
            raw = None
            with self.engine.transaction(True) as con:
                owner = self.engine._member(con)
                row = self._active(con, uid, owner)
                manifest = self.engine._manifest(row)
                current = next(s for s in manifest['slots'] if s['slotId'] == slot_id)
                if replayed:
                    if current['status'] == 'pending':
                        raise MediaError('conflict')
                else:
                    if (row['state'] != 'staging' or row['lease_token'] != lease
                            or row['lease_until'] <= self.engine.clock() or row['revision'] != revision
                            or current['status'] != 'pending'):
                        raise MediaError('conflict')
                    if error_code:
                        current.update(status='failed', error_code=error_code)
                    else:
                        self._store(con, row, current, preview)
                    con.execute('''UPDATE media_imports SET manifest_cipher=?,revision=revision+1,updated_at=?,
                        lease_token=NULL,lease_until=NULL,reserved_bytes=? WHERE id=?''',
                        (self.engine._seal('picker-manifest', row, manifest), self.engine.clock(),
                         sum(s['status'] == 'pending' for s in manifest['slots']) * ITEM_RESERVATION, uid))
                    self.engine._quota(con, owner)
            preview = None
        except BaseException as error:
            raw = preview = None
            _clear_video_error_frames(error)
            raise
        finally:
            # Error handlers must not retain raw/decoded buffers after the next
            # request is admitted. The sanitizer already removes decoder causes.
            raw = preview = None
            try:
                if lease:
                    with self.engine.transaction(True) as con:
                        con.execute('UPDATE media_imports SET lease_token=NULL,lease_until=NULL WHERE id=? AND lease_token=?',
                                    (uid, lease))
            finally:
                _UPLOAD_SLOT.release()
        return {**self.engine.import_detail(uid), 'replayed': replayed}

    def _store(self, con, row, slot, preview):
        source_key = self.engine.cipher.source_key(row['owner'], 'local-upload/v1', slot['sha256'])
        existing = con.execute("SELECT id,state,import_id FROM media_items WHERE owner=? AND source_key=? AND state!='deleted'",
                               (row['owner'], source_key)).fetchone()
        if existing:
            if existing['state'] == 'staged' and existing['import_id'] != row['id']:
                raise MediaError('conflict')
            slot.update(itemId=existing['id'], status='duplicate', error_code=None)
            return
        if con.execute('SELECT COUNT(*) FROM media_items WHERE owner=?', (row['owner'],)).fetchone()[0] >= 4000:
            raise MediaError('quota')
        item = {'id': slot['itemId'], 'owner': row['owner']}
        key = secrets.token_hex(12)
        metadata = {'source': SOURCE, 'sourceVersion': 1, 'accountId': None, 'sourceKey': source_key,
                    'previewKey': key, 'uploadSha256': slot['sha256'], 'displayFilename': slot['filename'],
                    'caption': '', 'sourceCreatedAt': None, 'width': preview.width, 'height': preview.height,
                    'contentType': 'image/jpeg', 'sha256': preview.sha256, 'bytes': len(preview.data), 'mediaType': 'photo'}
        con.execute('''INSERT INTO media_items
            (id,owner,account_id,import_id,source_key,state,metadata_cipher,preview_cipher,preview_key,created_at,updated_at)
            VALUES(?,?,NULL,?,?,'staged',?,?,?,?,?)''',
            (item['id'], item['owner'], row['id'], source_key, self.engine._seal('media-metadata', item, metadata),
             self.engine.cipher.seal_bytes('media-preview', preview.data), key, self.engine.clock(), self.engine.clock()))
        slot.update(status='successful', error_code=None)

    def finish(self, uid, value):
        _fields(value, {'revision', 'requestId'}, {'revision', 'requestId'})
        revision, request_id = _revision(value['revision']), _key(value['requestId'])
        with self.engine.transaction(True) as con:
            owner = self.engine._member(con)
            row = self.engine._import(con, uid, owner)
            if self.engine._import_source(row) != SOURCE:
                raise MediaError('not_found')
            context = self.engine._open('import-context', row, row['context_cipher'])
            digest = self.engine._receipt(owner, {'source': SOURCE, 'action': 'finish', 'id': uid, 'revision': revision})
            if context.get('finishRequestId'):
                if context['finishRequestId'] != request_id or context.get('finishKey') != digest:
                    raise MediaError('conflict')
                replayed = True
            else:
                replayed = False
                row = self._active(con, uid, owner)
                if row['state'] != 'staging' or row['revision'] != revision:
                    raise MediaError('conflict')
                if row['lease_token'] and row['lease_until'] > self.engine.clock():
                    raise MediaError('local_upload_busy')
                manifest = self.engine._manifest(row)
                for slot in manifest['slots']:
                    if slot['status'] == 'pending':
                        slot.update(status='skipped', error_code='local_upload_incomplete')
                context.update(finishRequestId=request_id, finishKey=digest)
                ready = any(s['status'] in ('successful', 'duplicate') for s in manifest['slots'])
                con.execute('''UPDATE media_imports SET state=?,revision=revision+1,context_cipher=?,manifest_cipher=?,
                    reserved_bytes=0,lease_token=NULL,lease_until=NULL,updated_at=? WHERE id=?''',
                    ('awaiting_confirmation' if ready else 'failed', self.engine._seal('import-context', row, context),
                     self.engine._seal('picker-manifest', row, manifest), self.engine.clock(), uid))
                if not ready:
                    current = self.engine._import(con, uid, owner)
                    con.execute('UPDATE media_imports SET context_cipher=?,manifest_cipher=NULL WHERE id=?',
                                (self.engine._terminal_receipt(current), uid))
                self.engine._quota(con, owner)
        return {**self.engine.import_detail(uid), 'replayed': replayed}


def register_local_uploads(app, engine, require_member):
    @app.post('/api/media/local-imports')
    def local_photo_create():
        require_member()
        result = engine.local_uploads.create(_request_object())
        return jsonify(result), 200 if result['replayed'] else 201

    @app.put('/api/media/local-imports/<uid>/files/<slot_id>')
    def local_photo_upload(uid, slot_id):
        require_member()
        value = request.headers.get('X-Import-Revision', '')
        if not re.fullmatch('[1-9][0-9]{0,15}', value):
            raise MediaError('invalid_input')
        return jsonify(engine.local_uploads.upload(uid, slot_id, int(value)))

    @app.post('/api/media/local-imports/<uid>/finish')
    def local_photo_finish(uid):
        require_member()
        return jsonify(engine.local_uploads.finish(uid, _request_object()))
