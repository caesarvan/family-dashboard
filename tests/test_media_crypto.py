"""Real cryptography with synthetic values; no app, account or network calls."""
import base64
import hashlib
import hmac
import json
import re

from cryptography.fernet import Fernet
import pytest

import media_crypto as media
from media_crypto import MediaCipher, MediaCryptoError


SECRET = 'synthetic-media-secret-0123456789'
HOUSEHOLD = 'default'
PURPOSES = sorted(media.JSON_PURPOSES)


@pytest.fixture
def cipher():
    return MediaCipher(SECRET, HOUSEHOLD)


def rejects(call):
    with pytest.raises(MediaCryptoError) as caught:
        call()
    error = caught.value
    assert str(error) == '媒体加密数据无效或无法处理'
    assert error.args == ('媒体加密数据无效或无法处理',)
    assert error.__cause__ is None and error.__context__ is None
    assert SECRET not in repr(error)
    return error


def reference_key(purpose, household=HOUSEHOLD, secret=SECRET):
    """Independent RFC 5869 extract + one expand block for format fixtures."""
    fields = [b'family-dashboard/media/v1', household.encode(), purpose.encode()]
    info = b''.join(len(value).to_bytes(4, 'big') + value for value in fields)
    prk = hmac.new(b'family-dashboard/media/v1', secret.encode(), hashlib.sha256).digest()
    return hmac.new(prk, info + b'\x01', hashlib.sha256).digest()


def forged_json(raw, purpose='media-metadata'):
    return Fernet(base64.urlsafe_b64encode(reference_key(purpose))).encrypt(raw)


def encoded(value, purpose='media-metadata'):
    return json.dumps({'version': 1, 'purpose': purpose, 'value': value},
                      ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode()


@pytest.mark.parametrize('purpose', PURPOSES)
def test_json_roundtrip_and_randomized_ciphertext(cipher, purpose):
    value = {'姓名': '虚构成员', 'state': ['合成', 3, -1.25, True, None], 'empty': {}}
    one = cipher.seal_json(purpose, value)
    two = cipher.seal_json(purpose, value)
    assert type(one) is bytes and one != two
    assert cipher.open_json(purpose, one) == value
    assert MediaCipher(SECRET, HOUSEHOLD).open_json(purpose, two) == value
    assert '虚构成员'.encode() not in one
    assert Fernet(base64.urlsafe_b64encode(reference_key(purpose))).decrypt(one) == encoded(value, purpose)


@pytest.mark.parametrize('value', [b'', b'\x00\xff\x80example\r\n', bytes(range(256))])
def test_binary_roundtrip(cipher, value):
    blob = cipher.seal_bytes('media-preview', value)
    assert cipher.open_bytes('media-preview', blob) == value
    assert MediaCipher(SECRET, HOUSEHOLD).open_bytes('media-preview', blob) == value


@pytest.mark.parametrize('first', PURPOSES)
@pytest.mark.parametrize('second', PURPOSES)
def test_json_keys_do_not_cross_purposes(cipher, first, second):
    blob = cipher.seal_json(first, {'synthetic': True})
    if first == second:
        assert cipher.open_json(second, blob) == {'synthetic': True}
    else:
        rejects(lambda: cipher.open_json(second, blob))


@pytest.mark.parametrize('secret,household', [(SECRET, 'second-home'), ('other-secret', HOUSEHOLD)])
def test_wrong_household_or_secret_fails_for_json_and_binary(cipher, secret, household):
    other = MediaCipher(secret, household)
    rejects(lambda: other.open_json('picker-session', cipher.seal_json('picker-session', {})))
    rejects(lambda: other.open_bytes('media-preview', cipher.seal_bytes('media-preview', b'data')))
    assert other.source_key('member1', 'subject', 'media') != cipher.source_key('member1', 'subject', 'media')


@pytest.mark.parametrize('purpose', [None, '', 'MEDIA-PREVIEW', ' media-preview', 'source-key', 'cloud-accounts-v1', [], 1])
def test_invalid_purpose_is_rejected_on_every_encryption_method(cipher, purpose):
    rejects(lambda: cipher.seal_json(purpose, {}))
    rejects(lambda: cipher.open_json(purpose, b'a' * 100))
    rejects(lambda: cipher.seal_bytes(purpose, b''))
    rejects(lambda: cipher.open_bytes(purpose, b'a' * 100))


def test_json_and_preview_methods_cannot_be_mixed(cipher):
    preview = cipher.seal_bytes('media-preview', b'{}')
    document = cipher.seal_json('picker-manifest', {})
    rejects(lambda: cipher.seal_json('media-preview', {}))
    rejects(lambda: cipher.open_json('media-preview', preview))
    rejects(lambda: cipher.open_json('picker-manifest', preview))
    rejects(lambda: cipher.seal_bytes('picker-manifest', b'{}'))
    rejects(lambda: cipher.open_bytes('picker-manifest', document))
    rejects(lambda: cipher.open_bytes('media-preview', document))


@pytest.mark.parametrize('value', [[], (), None, 'text', 0, True, {1: 'coerced'}, {'a': ()}, {'a': b'bytes'}, {'a': {1, 2}},
                                  {'a': float('nan')}, {'a': float('inf')}, {'a': -float('inf')}, {'a': '\ud800'}])
def test_json_rejects_non_object_non_json_and_invalid_unicode(cipher, value):
    rejects(lambda: cipher.seal_json('import-context', value))


@pytest.mark.parametrize('raw', [
    b'[]', b'null', b'{}', b'\xff', b'\xef\xbb\xbf{}',
    b'{"version":1,"purpose":"media-metadata","value":{},"extra":0}',
    b'{"version":2,"purpose":"media-metadata","value":{}}',
    b'{"version":true,"purpose":"media-metadata","value":{}}',
    b'{"version":1.0,"purpose":"media-metadata","value":{}}',
    b'{"version":1,"purpose":"picker-session","value":{}}',
    b'{"version":1,"purpose":"media-metadata","value":[]}',
    b'{"version":1,"purpose":"media-metadata","value":{},"value":{}}',
    b'{"version":1,"purpose":"media-metadata","value":{"a":1,"\\u0061":2}}',
    b'{"version":1,"purpose":"media-metadata","value":{"a":[{"x":1,"x":2}]}}',
    b'{"version":1,"purpose":"media-metadata","value":{"n":NaN}}',
    b'{"version":1,"purpose":"media-metadata","value":{"n":Infinity}}',
    b'{"version":1,"purpose":"media-metadata","value":{"n":-Infinity}}',
    b'{"version":1,"purpose":"media-metadata","value":{"n":1e999}}',
    b'{"version":1,"purpose":"media-metadata","value":{"s":"\\ud800"}}',
    b'{"version":1,"purpose":"media-metadata","value":{}} trailing',
])
def test_authenticated_but_invalid_json_envelope_is_rejected(cipher, raw):
    rejects(lambda: cipher.open_json('media-metadata', forged_json(raw)))


def test_json_byte_size_boundary_includes_envelope(cipher):
    overhead = len(encoded({'x': ''}))
    value = {'x': 'a' * (media.MAX_JSON_BYTES - overhead)}
    assert len(encoded(value)) == media.MAX_JSON_BYTES
    assert cipher.open_json('media-metadata', cipher.seal_json('media-metadata', value)) == value
    value['x'] += 'a'
    rejects(lambda: cipher.seal_json('media-metadata', value))
    # PKCS7/base64 roundoff can fit this extra byte in the encoded upper bound.
    token = forged_json(encoded(value))
    assert len(token) <= media._token_limit(media.MAX_JSON_BYTES)
    rejects(lambda: cipher.open_json('media-metadata', token))


def test_utf8_and_json_escaping_are_counted_as_bytes(cipher):
    overhead = len(encoded({'x': ''}))
    for unit in ['界', '\n', '"', '\\']:
        value = {'x': unit * ((media.MAX_JSON_BYTES - overhead) // len(json.dumps(unit, ensure_ascii=False)[1:-1].encode()))}
        assert cipher.open_json('media-metadata', cipher.seal_json('media-metadata', value)) == value
        value['x'] += unit
        rejects(lambda: cipher.seal_json('media-metadata', value))


def test_preview_size_boundary_and_authenticated_overflow(cipher):
    value = b'x' * media.MAX_PREVIEW_BYTES
    assert cipher.open_bytes('media-preview', cipher.seal_bytes('media-preview', value)) == value
    rejects(lambda: cipher.seal_bytes('media-preview', value + b'x'))
    key = Fernet(base64.urlsafe_b64encode(reference_key('media-preview')))
    rejects(lambda: cipher.open_bytes('media-preview', key.encrypt(media._PREVIEW_HEADER + value + b'x')))


@pytest.mark.parametrize('raw', [b'', b'raw-preview', b'family-dashboard/media/v2\x00media-preview\x00data',
                                 b'family-dashboard/media/v1\x00media-metadata\x00data'])
def test_authenticated_invalid_binary_version_is_rejected(cipher, raw):
    key = Fernet(base64.urlsafe_b64encode(reference_key('media-preview')))
    rejects(lambda: cipher.open_bytes('media-preview', key.encrypt(raw)))


def test_oversize_ciphertext_never_reaches_decode_or_decrypt(cipher, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail('Oversize ciphertext reached a decoder')
    monkeypatch.setattr(media.base64, 'b64decode', unexpected)
    monkeypatch.setattr(Fernet, 'decrypt', unexpected)
    rejects(lambda: cipher.open_json('picker-session', b'a' * (media._token_limit(media.MAX_JSON_BYTES) + 4)))
    rejects(lambda: cipher.open_bytes('media-preview', b'a' * (media._token_limit(media.MAX_PREVIEW_BYTES + len(media._PREVIEW_HEADER)) + 4)))


@pytest.mark.parametrize('location', [0, 1, 9, 25, -1])
def test_authenticated_ciphertext_tampering(cipher, location):
    token = cipher.seal_json('media-metadata', {'content': 'synthetic'})
    raw = bytearray(base64.urlsafe_b64decode(token))
    raw[location] ^= 1
    rejects(lambda: cipher.open_json('media-metadata', base64.urlsafe_b64encode(raw)))


@pytest.mark.parametrize('transform', [lambda x: x[:-1], lambda x: x + b'=', lambda x: b' ' + x,
                                        lambda x: x[:10] + b'\n' + x[10:], lambda x: b'!' * len(x),
                                        lambda x: x.decode(), lambda x: bytearray(x), lambda x: None])
def test_ciphertext_strict_encoding_and_type(cipher, transform):
    rejects(lambda: cipher.open_json('media-metadata', transform(cipher.seal_json('media-metadata', {}))))


def test_base64_padding_bits_and_alphabet_must_be_canonical(cipher):
    token = cipher.seal_json('media-metadata', {})
    alphabet = b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
    assert token.endswith(b'=')
    position = -3 if token.endswith(b'==') else -2
    changed = bytearray(token)
    changed[position] = alphabet[alphabet.index(changed[position]) | 1]
    assert base64.urlsafe_b64decode(changed) == base64.urlsafe_b64decode(token)
    rejects(lambda: cipher.open_json('media-metadata', bytes(changed)))
    # Replacing a urlsafe alphabet byte is still decodable by permissive APIs.
    modified = token.replace(b'-', b'+').replace(b'_', b'/')
    if modified != token:
        rejects(lambda: cipher.open_json('media-metadata', modified))


def test_depth_cycles_and_shared_values_are_bounded(cipher):
    cycle = {}
    cycle['cycle'] = cycle
    rejects(lambda: cipher.seal_json('picker-manifest', cycle))
    deep = {}
    for _ in range(media.MAX_JSON_DEPTH + 1):
        deep = {'nested': deep}
    rejects(lambda: cipher.seal_json('picker-manifest', deep))
    rejects(lambda: cipher.open_json('media-metadata', forged_json(encoded(deep))))
    shared = {'safe': [1, 2]}
    value = {'one': shared, 'two': shared}
    assert cipher.open_json('picker-manifest', cipher.seal_json('picker-manifest', value)) == value


@pytest.mark.parametrize('secret,household', [('', 'default'), (' ', 'default'), (None, 'default'), (b'secret', 'default'),
                                            ('x' * 65537, 'default'), ('界' * 21846, 'default'), ('\ud800', 'default'),
                                            (SECRET, ''), (SECRET, '  '), (SECRET, None), (SECRET, 123),
                                            (SECRET, 'x' * 257), (SECRET, '界' * 86), (SECRET, '\ud800')],
                         ids=[f'invalid-input-{index}' for index in range(14)])
def test_constructor_strict_nonempty_utf8_bounded_inputs(secret, household):
    rejects(lambda: MediaCipher(secret, household))


@pytest.mark.parametrize('household', ['default', '1' * 24, '家庭 甲', ' home ', '界' * 85])
def test_existing_household_ids_and_secret_strings_are_supported(household):
    cipher = MediaCipher('test-secret', household)
    assert cipher.open_json('import-context', cipher.seal_json('import-context', {})) == {}
    assert repr(cipher) == '<MediaCipher>' and not hasattr(cipher, '__dict__')


def test_exact_constructor_byte_limits_and_legacy_cloud_key_isolation():
    cipher = MediaCipher('界' * 21845 + 'x', '界' * 85 + 'x')
    assert cipher.open_json('picker-session', cipher.seal_json('picker-session', {})) == {}
    cipher = MediaCipher(SECRET, HOUSEHOLD)
    legacy = Fernet(base64.urlsafe_b64encode(hashlib.sha256((SECRET + '|cloud-accounts-v1').encode()).digest()))
    rejects(lambda: cipher.open_json('picker-session', legacy.encrypt(encoded({}, 'picker-session'))))


@pytest.mark.parametrize('value', [None, 'text', bytearray(b'data'), memoryview(b'data')])
def test_preview_seal_requires_bytes(cipher, value):
    rejects(lambda: cipher.seal_bytes('media-preview', value))


def test_source_key_stable_and_owner_subject_media_household_secret_isolated(cipher):
    original = cipher.source_key('member1', 'google-subject', 'selected-media')
    assert re.fullmatch('[0-9a-f]{64}', original)
    assert original == MediaCipher(SECRET, HOUSEHOLD).source_key('member1', 'google-subject', 'selected-media')
    others = [cipher.source_key('member2', 'google-subject', 'selected-media'),
              cipher.source_key('member1', 'other-subject', 'selected-media'),
              cipher.source_key('member1', 'google-subject', 'other-media'),
              MediaCipher(SECRET, 'other').source_key('member1', 'google-subject', 'selected-media'),
              MediaCipher('other-secret', HOUSEHOLD).source_key('member1', 'google-subject', 'selected-media')]
    assert len(set([original, *others])) == 6
    parts = [media.NAMESPACE, b'member1', b'google-subject', b'selected-media']
    message = b''.join(len(part).to_bytes(4, 'big') + part for part in parts)
    assert original == hmac.new(reference_key('source-key'), message, hashlib.sha256).hexdigest()
    assert len({reference_key(p) for p in [*PURPOSES, 'media-preview', 'source-key']}) == 6


@pytest.mark.parametrize('left,right', [(('ab', 'c', 'd'), ('a', 'bc', 'd')),
                                       (('a', 'b|c', 'd'), ('a|b', 'c', 'd')),
                                       (('a', 'b\x00c', 'd'), ('a\x00b', 'c', 'd')),
                                       (('é', 's', 'm'), ('e\u0301', 's', 'm')),
                                       (('a', 's', 'm'), (' a', 's', 'm'))])
def test_source_key_input_framing_has_no_concatenation_or_normalization_alias(cipher, left, right):
    assert cipher.source_key(*left) != cipher.source_key(*right)


@pytest.mark.parametrize('position,limit', [(0, 256), (1, 1024), (2, 4096)])
def test_source_key_fields_have_strict_utf8_and_length_bounds(cipher, position, limit):
    parts = ['member1', 'subject', 'media']
    parts[position] = 'x' * limit
    assert len(cipher.source_key(*parts)) == 64
    for value in ['', ' ', None, b'x', 2, '\ud800', 'x' * (limit + 1), '界' * (limit // 3 + 1)]:
        parts[position] = value
        rejects(lambda: cipher.source_key(*parts))


def test_errors_discard_cause_context_and_sensitive_exception_repr(cipher, caplog):
    marker = 'synthetic-sensitive-token-or-plaintext'
    class Broken:
        def encrypt(self, _value):
            raise RuntimeError(marker)
        def decrypt(self, _value):
            raise RuntimeError(marker)
    valid = cipher.seal_json('media-metadata', {})
    cipher._ciphers['media-metadata'] = Broken()
    for call in [lambda: cipher.seal_json('media-metadata', {}), lambda: cipher.open_json('media-metadata', valid)]:
        error = rejects(call)
        assert marker not in str(error) + repr(error)
    assert not caplog.records
