"""Video cache format and bounds with real cryptography, entirely synthetic data."""
import base64
import sqlite3

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import pytest

import media_crypto as media
from media_crypto import MediaCipher
from media_video_storage import SCHEMA_SQL, initialize_media_video_storage
from test_media_crypto import SECRET, HOUSEHOLD, reference_key, rejects


HEADER = b'family-dashboard/media/v1\x00media-video/aesgcm/v1\x00'
KEY_DOMAIN = 'media-video/aesgcm/v1'


@pytest.fixture
def cipher():
    return MediaCipher(SECRET, HOUSEHOLD)


@pytest.mark.parametrize('value', [b'', b'\x00\xffsynthetic', bytes(range(256))])
def test_video_format_independent_key_reference_and_restart(cipher, value):
    blob = cipher.seal_bytes('media-video', value)
    assert blob.startswith(HEADER)
    assert len(blob) == len(value) + len(HEADER) + 12 + 16
    nonce = blob[len(HEADER):len(HEADER) + 12]
    assert AESGCM(reference_key(KEY_DOMAIN)).decrypt(nonce, blob[len(HEADER) + 12:], HEADER) == value
    assert MediaCipher(SECRET, HOUSEHOLD).open_bytes('media-video', blob) == value
    # Independently constructed envelope can be read by the production helper.
    other_nonce = b'fixed-tests!'  # Synthetic test fixture only; exactly 12 bytes.
    other = HEADER + other_nonce + AESGCM(reference_key(KEY_DOMAIN)).encrypt(other_nonce, value, HEADER)
    assert cipher.open_bytes('media-video', other) == value


def test_video_random_nonce_each_seal(cipher):
    blobs = [cipher.seal_bytes('media-video', b'same synthetic value') for _ in range(16)]
    assert len({blob[len(HEADER):len(HEADER) + 12] for blob in blobs}) == 16
    assert all(cipher.open_bytes('media-video', blob) == b'same synthetic value' for blob in blobs)


@pytest.mark.parametrize('location', [0, len(HEADER) - 2, len(HEADER), len(HEADER) + 12, -1])
def test_header_nonce_ciphertext_and_tag_tampering_rejected(cipher, location):
    changed = bytearray(cipher.seal_bytes('media-video', b'synthetic payload'))
    changed[location] ^= 1
    rejects(lambda: cipher.open_bytes('media-video', bytes(changed)))


def test_authenticated_wrong_aad_and_domain_rejected(cipher):
    nonce = b'fixed-tests!'
    key = AESGCM(reference_key(KEY_DOMAIN))
    wrong_aad = HEADER + nonce + key.encrypt(nonce, b'value', HEADER + b'other')
    rejects(lambda: cipher.open_bytes('media-video', wrong_aad))
    old_key = AESGCM(reference_key('media-video'))
    wrong_key = HEADER + nonce + old_key.encrypt(nonce, b'value', HEADER)
    rejects(lambda: cipher.open_bytes('media-video', wrong_key))


@pytest.mark.parametrize('secret, household', [(SECRET, 'other-home'), ('other-secret', HOUSEHOLD)])
def test_video_isolated_by_secret_household_and_purpose(cipher, secret, household):
    blob = cipher.seal_bytes('media-video', b'synthetic payload')
    rejects(lambda: MediaCipher(secret, household).open_bytes('media-video', blob))
    rejects(lambda: cipher.open_bytes('media-preview', blob))
    rejects(lambda: cipher.open_json('media-metadata', blob))
    rejects(lambda: cipher.open_bytes('media-video', cipher.seal_bytes('media-preview', b'value')))
    rejects(lambda: cipher.open_bytes('media-video', cipher.seal_json('media-metadata', {})))


def test_unreleased_fernet_video_and_unknown_version_rejected(cipher):
    old = Fernet(base64.urlsafe_b64encode(reference_key('media-video'))).encrypt(
        b'family-dashboard/media/v1\x00media-video\x00synthetic')
    rejects(lambda: cipher.open_bytes('media-video', old))
    blob = cipher.seal_bytes('media-video', b'synthetic')
    rejects(lambda: cipher.open_bytes('media-video', blob.replace(b'aesgcm/v1', b'aesgcm/v2', 1)))


@pytest.mark.parametrize('value', [None, 'text', bytearray(b'data'), memoryview(b'data')])
def test_video_requires_immutable_bytes(cipher, value):
    rejects(lambda: cipher.seal_bytes('media-video', value))
    rejects(lambda: cipher.open_bytes('media-video', value))


@pytest.mark.parametrize('transform', [lambda x: b'', lambda x: x[:len(HEADER) + 27],
                                    lambda x: x[:-1], lambda x: x + b'\x00'])
def test_video_truncation_and_extension_rejected(cipher, transform):
    blob = cipher.seal_bytes('media-video', b'synthetic')
    rejects(lambda: cipher.open_bytes('media-video', transform(blob)))


def test_full_64mib_exact_bound_and_overflow_before_crypto(cipher):
    value = b'x' * media.MAX_VIDEO_BYTES
    blob = cipher.seal_bytes('media-video', value)
    assert media.MAX_VIDEO_BYTES == 64 * 1024 * 1024
    assert len(blob) == media.MAX_VIDEO_CIPHER_BYTES == len(value) + len(HEADER) + 28
    assert cipher.open_bytes('media-video', blob) == value
    class Unreachable:
        def encrypt(self, *args):
            pytest.fail('Oversize plaintext reached encryption')
        def decrypt(self, *args):
            pytest.fail('Oversize ciphertext reached decryption')
    cipher._video_cipher = Unreachable()
    rejects(lambda: cipher.seal_bytes('media-video', value + b'x'))
    rejects(lambda: cipher.open_bytes('media-video', blob + b'x'))
    rejects(lambda: cipher.open_bytes('media-video', b'x' * len(HEADER)))


def test_crypto_failure_has_no_sensitive_context_or_logs(cipher, caplog):
    marker = 'synthetic-secret-plaintext'
    blob = cipher.seal_bytes('media-video', b'value')
    class Broken:
        def encrypt(self, *args):
            raise RuntimeError(marker)
        def decrypt(self, *args):
            raise RuntimeError(marker)
    cipher._video_cipher = Broken()
    for call in [lambda: cipher.seal_bytes('media-video', b'value'),
                 lambda: cipher.open_bytes('media-video', blob)]:
        error = rejects(call)
        assert marker not in str(error) + repr(error)
    assert not caplog.records


def test_video_storage_uses_cipher_bound_and_rejects_old_candidate_schema():
    con = sqlite3.connect(':memory:')
    con.execute('PRAGMA foreign_keys=ON')
    for name in ('media_items', 'media_imports', 'media_tv_grants'):
        con.execute(f'CREATE TABLE {name}(id TEXT PRIMARY KEY)')
    initialize_media_video_storage(con)
    sql = con.execute("SELECT sql FROM sqlite_master WHERE name='media_video_cache'").fetchone()[0]
    assert f'length(cipher)<={media.MAX_VIDEO_CIPHER_BYTES}' in sql
    con.execute("INSERT INTO media_items VALUES('synthetic-id')")
    con.execute('INSERT INTO media_video_cache VALUES(?,?,?,?)', ('synthetic-id', 'key', b'x', 1))
    con.commit()
    with pytest.raises(sqlite3.IntegrityError):
        con.execute('UPDATE media_video_cache SET cipher=zeroblob(?)', (media.MAX_VIDEO_CIPHER_BYTES + 1,))
    con.rollback()
    con.execute('DROP TABLE media_video_cache')
    con.executescript(SCHEMA_SQL.replace(str(media.MAX_VIDEO_CIPHER_BYTES), '89478628'))
    with pytest.raises(RuntimeError, match='schema differs'):
        initialize_media_video_storage(con)
    con.close()
