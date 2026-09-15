"""Real Flask API coverage for photo sharing boundaries and procurement estimates."""
import base64
from io import BytesIO
import sqlite3
import time

from PIL import Image
import pytest

from test_app import app, member


def image_data(format='PNG', size=(8, 6), exif=None):
    stream = BytesIO()
    picture = Image.new('RGB', size, '#9ad1b1')
    picture.save(stream, format=format, **({'exif': exif} if exif else {}))
    mime = {'PNG': 'png', 'JPEG': 'jpeg', 'WEBP': 'webp', 'GIF': 'gif'}[format]
    return f'data:image/{mime};base64,' + base64.b64encode(stream.getvalue()).decode('ascii')


def upload(client, headers, data=None):
    result = client.post('/api/photos', json={'dataUrl': data or image_data()}, headers=headers)
    assert result.status_code == 201, result.json
    return result.json['id']


def create(client, headers, **fields):
    response = client.post('/api/items/shopping', json={'title': '采购测试', **fields}, headers=headers)
    assert response.status_code == 201, response.json
    return response.json['id']


def pair_tv(app, client, headers):
    tv = app.test_client()
    pair = tv.post('/api/pair/start', json={}).json
    approved = client.post('/api/pair/approve', json={'code': pair['code'], 'name': '测试电视', 'focus': 'member1'}, headers=headers)
    assert approved.status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    return tv


def test_photos_only_shared_after_attachment_then_removed(app):
    owner, headers = member(app)
    partner, partner_headers = member(app, 2)
    tv = pair_tv(app, owner, headers)
    photo_id = upload(owner, headers)
    photo_url = '/api/photos/' + photo_id
    assert app.test_client().get(photo_url).status_code == 401
    assert owner.get(photo_url).status_code == 200
    assert partner.get(photo_url).status_code == 404
    assert tv.get(photo_url).status_code == 404
    unauthorized = partner.post('/api/items/shopping', json={'title': '无权附加', 'photoIds': [photo_id]}, headers=partner_headers)
    assert unauthorized.status_code == 400
    assert partner.get('/api/state').json['shopping'] == []
    item_id = create(owner, headers, photoIds=[photo_id])
    assert partner.get(photo_url).status_code == 200
    assert tv.get(photo_url).status_code == 200
    assert tv.post('/api/photos', json={'dataUrl': image_data()}, headers=headers).status_code == 403
    # Either member may edit a shared item and remove its shared photo reference.
    removed = partner.patch('/api/items/shopping/' + item_id, json={'revision': 1, 'photoIds': []}, headers=partner_headers)
    assert removed.status_code == 200
    assert owner.get(photo_url).status_code == 200
    assert partner.get(photo_url).status_code == 404
    assert tv.get(photo_url).status_code == 404


def test_photos_auth_csrf_origin_headers(app):
    owner, headers = member(app)
    assert app.test_client().post('/api/photos', json={'dataUrl': image_data()}).status_code == 401
    assert owner.post('/api/photos', json={'dataUrl': image_data()}).status_code == 403
    assert owner.post('/api/photos', json={'dataUrl': image_data()}, headers={**headers, 'Origin': 'https://other.test'}).status_code == 403
    uid = upload(owner, headers)
    photo = owner.get('/api/photos/' + uid)
    assert photo.mimetype == 'image/jpeg'
    assert photo.headers['Cache-Control'] == 'no-store'
    assert photo.headers['X-Content-Type-Options'] == 'nosniff'


@pytest.mark.parametrize('value', [None, 0, 12345])
def test_procurement_amounts_preserve_null_and_zero(app, value):
    owner, headers = member(app)
    create(owner, headers, budget=value, actual=value)
    item = owner.get('/api/state').json['shopping'][0]
    assert item['budget'] == value and item['actual'] == value
    assert item['photoIds'] == []
    assert owner.get('/api/state').json['finance']['livingSpent'] == 0


@pytest.mark.parametrize('value', [-1, True, False, 1.5, '100', 100000000001])
def test_procurement_rejects_invalid_amounts(app, value):
    owner, headers = member(app)
    for key in ('budget', 'actual'):
        response = owner.post('/api/items/shopping', json={'title': '错误金额', key: value}, headers=headers)
        assert response.status_code == 400, (key, value, response.json)
    assert owner.get('/api/state').json['shopping'] == []


@pytest.mark.parametrize('value', [None, [], {}, 123, 'data:image/svg+xml;base64,PHN2Zz4=', 'data:image/jpeg;base64,bm90YW5pbWFnZQ==', 'data:image/png;base64,%%%%', 'data:image/png;base64,aaaaa'])
def test_rejects_invalid_photo_body(app, value):
    owner, headers = member(app)
    assert owner.post('/api/photos', json={'dataUrl': value}, headers=headers).status_code == 400


def test_rejects_disguised_gif_and_oversized_dimensions(app):
    owner, headers = member(app)
    disguised = image_data('GIF').replace('image/gif', 'image/png')
    assert owner.post('/api/photos', json={'dataUrl': disguised}, headers=headers).status_code == 400
    assert owner.post('/api/photos', json={'dataUrl': image_data(size=(4001, 3000))}, headers=headers).status_code == 400


def test_three_photos_max_invalid_ids_and_atomic_refs(app):
    owner, headers = member(app)
    partner, _ = member(app, 2)
    ids = [upload(owner, headers) for _ in range(4)]
    for invalid in (ids, [ids[0], ids[0]], ['../bad'], 'not-list', [123]):
        response = owner.post('/api/items/shopping', json={'title': '无效图片', 'photoIds': invalid}, headers=headers)
        assert response.status_code == 400
    item_id = create(owner, headers, photoIds=ids[:3], budget=5000)
    path = '/api/items/shopping/' + item_id
    # A rejected reference must roll back the item update and all old references.
    response = owner.patch(path, json={'revision': 1, 'title': '不应保存', 'photoIds': ['f' * 32]}, headers=headers)
    assert response.status_code == 400
    item = owner.get('/api/state').json['shopping'][0]
    assert item['title'] == '采购测试' and item['revision'] == 1 and item['photoIds'] == ids[:3]
    assert all(partner.get('/api/photos/' + uid).status_code == 200 for uid in ids[:3])
    assert owner.patch(path, json={'revision': 1, 'done': True}, headers=headers).status_code == 200
    assert owner.patch(path, json={'revision': 1, 'photoIds': [ids[3]]}, headers=headers).status_code == 409
    assert partner.get('/api/photos/' + ids[3]).status_code == 404
    item = owner.get('/api/state').json['shopping'][0]
    assert item['photoIds'] == ids[:3] and item['budget'] == 5000
    assert owner.delete(path, json={'revision': 2}, headers=headers).status_code == 200
    assert all(partner.get('/api/photos/' + uid).status_code == 404 for uid in ids)


def test_image_reencode_strips_exif_and_honors_orientation(app):
    owner, headers = member(app)
    exif = Image.Exif()
    exif[274] = 6  # Rotate 90 degrees clockwise.
    exif[315] = 'Private account holder'
    exif[270] = 'Sensitive address'
    uid = upload(owner, headers, image_data('JPEG', size=(8, 6), exif=exif))
    response = owner.get('/api/photos/' + uid)
    with Image.open(BytesIO(response.data)) as clean:
        assert clean.format == 'JPEG' and clean.size == (6, 8)
        assert not clean.getexif()
        assert 'icc_profile' not in clean.info
    assert b'Private account holder' not in response.data and b'Sensitive address' not in response.data


def test_only_expired_orphans_are_cleaned(app):
    owner, headers = member(app)
    old_orphan = upload(owner, headers)
    attached = upload(owner, headers)
    recent_orphan = upload(owner, headers)
    create(owner, headers, photoIds=[attached])
    with sqlite3.connect(str(app.config['DATA_DIR']) + '/household.sqlite3') as conn:
        conn.execute('UPDATE photos SET created_at=? WHERE id IN (?,?)', (time.time() - 90000, old_orphan, attached))
    upload(owner, headers)
    assert owner.get('/api/photos/' + old_orphan).status_code == 404
    assert owner.get('/api/photos/' + attached).status_code == 200
    assert owner.get('/api/photos/' + recent_orphan).status_code == 200


def test_decoder_busy_rejects_without_writing_then_recovers(app):
    from shopping_media import DECODE_SLOT
    owner, headers = member(app)
    assert DECODE_SLOT.acquire(blocking=False)
    try:
        response = owner.post('/api/photos', json={'dataUrl': image_data()}, headers=headers)
        assert response.status_code == 429
    finally:
        DECODE_SLOT.release()
    assert upload(owner, headers)


def test_decoder_releases_slot_after_invalid_picture(app):
    owner, headers = member(app)
    assert owner.post('/api/photos', json={'dataUrl': 'data:image/png;base64,bm90YW5pbWFnZQ=='}, headers=headers).status_code == 400
    assert upload(owner, headers)


def test_server_pixel_cap_accepts_browser_output_and_rejects_over_four_million(app):
    owner, headers = member(app)
    assert upload(owner, headers, image_data(size=(1600, 1600)))
    assert owner.post('/api/photos', json={'dataUrl': image_data(size=(2001, 2000))}, headers=headers).status_code == 400
    # The size-rejection path must also free the decoder slot.
    assert upload(owner, headers)
