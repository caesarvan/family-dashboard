"""Authenticated shopping photos, stored with the SQLite backup and stripped of metadata."""
import base64
import binascii
from io import BytesIO
import re
import secrets
import time
import warnings
from threading import BoundedSemaphore

from flask import g, jsonify, Response
from PIL import Image, ImageOps, UnidentifiedImageError

DECODE_SLOT = BoundedSemaphore(1)


def validate_photo_ids(value, Problem):
    if not isinstance(value, list) or len(value) > 3 or any(
        not isinstance(uid, str) or not re.fullmatch(r'[a-f0-9]{32}', uid) for uid in value
    ) or len(set(value)) != len(value):
        raise Problem('每件物品最多添加 3 张图片')
    return value


def sync_photo_refs(conn, entity_id, photo_ids, owner, Problem):
    # Called in the entity write transaction: rejected photos roll back the item too.
    for uid in photo_ids:
        row = conn.execute('SELECT created_by FROM photos WHERE id=?', (uid,)).fetchone()
        attached = conn.execute('SELECT 1 FROM photo_refs WHERE photo_id=?', (uid,)).fetchone()
        if not row or (row['created_by'] != owner and not attached):
            raise Problem('图片不存在或无权使用，请重新上传', 400)
    conn.execute('DELETE FROM photo_refs WHERE entity_id=?', (entity_id,))
    conn.executemany('INSERT INTO photo_refs(photo_id,entity_id) VALUES(?,?)',
                     [(uid, entity_id) for uid in photo_ids])


def register_media(app, db, Problem, body, limited):
    with app.app_context():
        db().executescript('''
        CREATE TABLE IF NOT EXISTS photos(
          id TEXT PRIMARY KEY, content BLOB NOT NULL, size INTEGER NOT NULL,
          width INTEGER NOT NULL, height INTEGER NOT NULL,
          created_by TEXT NOT NULL REFERENCES users(id), created_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS photo_refs(
          photo_id TEXT NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
          entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
          PRIMARY KEY(photo_id,entity_id));
        CREATE INDEX IF NOT EXISTS photo_refs_entity ON photo_refs(entity_id);
        ''')
        db().commit()

    @app.post('/api/photos')
    def upload_photo():
        limited('photo_upload', 30)
        value = body().get('dataUrl')
        match = re.fullmatch(r'data:image/(?:jpeg|png|webp);base64,([A-Za-z0-9+/=]+)', value or '') if isinstance(value, str) else None
        if not match or len(value) > 7_000_000:
            raise Problem('请上传 JPG、PNG 或 WebP 图片，压缩后不超过 5 MB')
        if not DECODE_SLOT.acquire(blocking=False):
            raise Problem('正在处理另一张图片，请稍后重试', 429)
        try:
            raw = base64.b64decode(match[1], validate=True)
            if len(raw) > 5_000_000:
                raise Problem('图片过大，请缩小后重试', 413)
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(BytesIO(raw)) as source:
                    if source.format not in {'JPEG', 'PNG', 'WEBP'} or source.width * source.height > 4_000_000:
                        raise Problem('图片尺寸过大或格式不支持，请压缩后重试')
                    source.load()
                    picture = ImageOps.exif_transpose(source)
                    picture.thumbnail((1600, 1600))
                    # A fresh RGB canvas removes EXIF, GPS, comments and color profiles.
                    clean = Image.new('RGB', picture.size, 'white')
                    rgba = picture.convert('RGBA')
                    clean.paste(rgba, mask=rgba.getchannel('A'))
                    output = BytesIO()
                    clean.save(output, format='JPEG', quality=85, optimize=True)
                    width, height = clean.size
                    content = output.getvalue()
        except (ValueError, binascii.Error, UnidentifiedImageError, OSError,
                Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise Problem('无法读取这张图片，请改用 JPG、PNG 或 WebP')
        finally:
            DECODE_SLOT.release()
        if len(content) > 2_000_000:
            raise Problem('图片过大，请缩小后重试', 413)
        conn = db()
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('DELETE FROM photos WHERE created_at<? AND NOT EXISTS '
                     '(SELECT 1 FROM photo_refs WHERE photo_refs.photo_id=photos.id)', (time.time()-86400,))
        count, size = conn.execute('SELECT count(*),coalesce(sum(size),0) FROM photos').fetchone()
        if count >= 500 or size + len(content) > 200_000_000:
            raise Problem('图片空间已满，请整理不再需要的采购照片')
        uid = secrets.token_hex(16)
        conn.execute('INSERT INTO photos VALUES(?,?,?,?,?,?,?)',
                     (uid, content, len(content), width, height, g.actor['id'], time.time()))
        conn.commit()
        return jsonify(id=uid, url='/api/photos/'+uid), 201

    @app.get('/api/photos/<uid>')
    def get_photo(uid):
        row = db().execute('SELECT * FROM photos WHERE id=?', (uid,)).fetchone()
        attached = db().execute('SELECT 1 FROM photo_refs WHERE photo_id=?', (uid,)).fetchone()
        own = row and g.actor['role'] == 'member' and row['created_by'] == g.actor['id']
        if not row or not (attached or own):
            raise Problem('图片不存在', 404)
        return Response(bytes(row['content']), mimetype='image/jpeg',
                        headers={'Content-Disposition': 'inline; filename="shopping.jpg"'})
