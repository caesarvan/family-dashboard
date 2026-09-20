"""Bounded household/purpose encryption for media data, without authorization.

No application, storage, network or logging integration. Callers must authorize
the owner and household before using this helper or returning decrypted data.
"""
from __future__ import annotations

import base64
from functools import wraps
import hashlib
import hmac
import json
import math
import os

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


NAMESPACE = b'family-dashboard/media/v1'
JSON_PURPOSES = frozenset({'import-context', 'picker-session', 'picker-manifest', 'media-metadata'})
PREVIEW_PURPOSE = 'media-preview'
VIDEO_PURPOSE = 'media-video'
MAX_JSON_BYTES = 256 * 1024
MAX_PREVIEW_BYTES = 2 * 1024 * 1024
MAX_VIDEO_BYTES = 64 * 1024 * 1024
MAX_JSON_DEPTH = 64
_PREVIEW_HEADER = NAMESPACE + b'\x00media-preview\x00'
_VIDEO_KEY_PURPOSE = 'media-video/aesgcm/v1'
_VIDEO_HEADER = NAMESPACE + b'\x00media-video/aesgcm/v1\x00'
_VIDEO_NONCE_BYTES = 12
_VIDEO_TAG_BYTES = 16
_VIDEO_OVERHEAD = len(_VIDEO_HEADER) + _VIDEO_NONCE_BYTES + _VIDEO_TAG_BYTES
_BINARY = {PREVIEW_PURPOSE: (MAX_PREVIEW_BYTES, _PREVIEW_HEADER)}
_ERROR = '媒体加密数据无效或无法处理'


class MediaCryptoError(Exception):
    """A fixed safe error; it carries no original exception or input values."""

    def __init__(self):
        super().__init__(_ERROR)


def _safe(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception:
            pass
        # Outside the handler: neither __context__ nor __cause__ retains the
        # original exception. Do not attach raw input or exception diagnostics.
        raise MediaCryptoError() from None
    return guarded


def _text(value, limit):
    if type(value) is not str or len(value) > limit or not value.strip():
        raise ValueError()
    raw = value.encode('utf-8', errors='strict')
    if len(raw) > limit:
        raise ValueError()
    return raw


def _frame(*parts):
    return b''.join(len(part).to_bytes(4, 'big') + part for part in parts)


def _token_limit(plaintext_limit):
    # Fernet: 1 version + 8 timestamp + 16 IV + padded AES + 32 HMAC;
    # PKCS7 adds one full block when the plaintext is block-aligned.
    raw_size = 57 + 16 * (plaintext_limit // 16 + 1)
    return 4 * ((raw_size + 2) // 3)


MAX_VIDEO_CIPHER_BYTES = MAX_VIDEO_BYTES + _VIDEO_OVERHEAD


def _validate_json(value):
    """Only JSON builtins, bounded depth/work, finite numbers and strict UTF-8."""
    active = set()
    budget = MAX_JSON_BYTES

    def walk(item, depth):
        nonlocal budget
        budget -= 1
        if budget < 0 or depth > MAX_JSON_DEPTH:
            raise ValueError()
        kind = type(item)
        if kind is str:
            if len(item) > MAX_JSON_BYTES:
                raise ValueError()
            budget -= len(item.encode('utf-8', errors='strict'))
        elif kind is float:
            if not math.isfinite(item):
                raise ValueError()
        elif kind in (int, bool, type(None)):
            pass
        elif kind in (dict, list):
            if id(item) in active or len(item) > MAX_JSON_BYTES:
                raise ValueError()
            active.add(id(item))
            if kind is dict:
                for key, child in item.items():
                    if type(key) is not str:
                        raise ValueError()
                    walk(key, depth)
                    walk(child, depth + 1)
            else:
                for child in item:
                    walk(child, depth + 1)
            active.remove(id(item))
        else:
            raise ValueError()
        if budget < 0:
            raise ValueError()

    walk(value, 0)


def _encode_json(value):
    _validate_json(value)
    encoded = bytearray()
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(',', ':'), sort_keys=True)
    for chunk in encoder.iterencode(value):
        raw = chunk.encode('utf-8', errors='strict')
        if len(encoded) + len(raw) > MAX_JSON_BYTES:
            raise ValueError()
        encoded.extend(raw)
    return bytes(encoded)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def _constant(_value):
    raise ValueError()


class MediaCipher:
    """Derive independent v1 keys from a server secret and an exact household id."""

    __slots__ = ('_ciphers', '_source_key', '_video_cipher')

    @_safe
    def __init__(self, secret_key: str, household_id: str):
        secret = _text(secret_key, 65536)
        household = _text(household_id, 256)

        def derive(purpose):
            return HKDF(algorithm=hashes.SHA256(), length=32, salt=NAMESPACE,
                        info=_frame(NAMESPACE, household, purpose.encode('ascii'))).derive(secret)

        self._ciphers = {purpose: Fernet(base64.urlsafe_b64encode(derive(purpose)))
                         for purpose in (*sorted(JSON_PURPOSES), *_BINARY)}
        self._source_key = derive('source-key')
        self._video_cipher = AESGCM(derive(_VIDEO_KEY_PURPOSE))

    def __repr__(self):
        return '<MediaCipher>'

    def _cipher(self, purpose, allowed):
        if type(purpose) is not str or purpose not in allowed:
            raise ValueError()
        return self._ciphers[purpose]

    def _decrypt(self, cipher, blob, plaintext_limit):
        if type(blob) is not bytes or not 100 <= len(blob) <= _token_limit(plaintext_limit) or len(blob) % 4:
            raise ValueError()
        # Reject whitespace, alternate alphabets, invalid padding and other
        # noncanonical encodings before Fernet's permissive base64 decoder.
        raw = base64.b64decode(blob, altchars=b'-_', validate=True)
        if base64.urlsafe_b64encode(raw) != blob:
            raise ValueError()
        plaintext = cipher.decrypt(blob)
        if len(plaintext) > plaintext_limit:
            raise ValueError()
        return plaintext

    @_safe
    def seal_json(self, purpose: str, value: dict) -> bytes:
        cipher = self._cipher(purpose, JSON_PURPOSES)
        if type(value) is not dict:
            raise ValueError()
        return cipher.encrypt(_encode_json({'version': 1, 'purpose': purpose, 'value': value}))

    @_safe
    def open_json(self, purpose: str, blob: bytes) -> dict:
        cipher = self._cipher(purpose, JSON_PURPOSES)
        plaintext = self._decrypt(cipher, blob, MAX_JSON_BYTES)
        value = json.loads(plaintext.decode('utf-8', errors='strict'),
                           object_pairs_hook=_object, parse_constant=_constant)
        _validate_json(value)
        if (type(value) is not dict or set(value) != {'version', 'purpose', 'value'}
                or type(value['version']) is not int or value['version'] != 1
                or value['purpose'] != purpose or type(value['value']) is not dict):
            raise ValueError()
        return value['value']

    @_safe
    def seal_bytes(self, purpose: str, value: bytes) -> bytes:
        if type(purpose) is str and purpose == VIDEO_PURPOSE:
            if type(value) is not bytes or len(value) > MAX_VIDEO_BYTES:
                raise ValueError()
            nonce = os.urandom(_VIDEO_NONCE_BYTES)
            # A separate key domain and authenticated version header; JPEG/JSON
            # retain their original Fernet format and key derivation unchanged.
            encrypted = self._video_cipher.encrypt(nonce, value, _VIDEO_HEADER)
            return b''.join((_VIDEO_HEADER, nonce, encrypted))
        cipher = self._cipher(purpose, _BINARY)
        limit, header = _BINARY[purpose]
        if type(value) is not bytes or len(value) > limit:
            raise ValueError()
        return cipher.encrypt(header + value)

    @_safe
    def open_bytes(self, purpose: str, blob: bytes) -> bytes:
        if type(purpose) is str and purpose == VIDEO_PURPOSE:
            if (type(blob) is not bytes
                    or not _VIDEO_OVERHEAD <= len(blob) <= MAX_VIDEO_CIPHER_BYTES
                    or not blob.startswith(_VIDEO_HEADER)):
                raise ValueError()
            boundary = len(_VIDEO_HEADER) + _VIDEO_NONCE_BYTES
            nonce = blob[len(_VIDEO_HEADER):boundary]
            # Avoid copying up to 64 MiB just to remove the framing. AESGCM
            # returns plaintext only after authenticating the entire tag/AAD.
            return self._video_cipher.decrypt(nonce, memoryview(blob)[boundary:], _VIDEO_HEADER)
        cipher = self._cipher(purpose, _BINARY)
        limit, header = _BINARY[purpose]
        plaintext = self._decrypt(cipher, blob, limit + len(header))
        if not plaintext.startswith(header):
            raise ValueError()
        return plaintext[len(header):]

    @_safe
    def source_key(self, owner: str, account_subject: str, media_id: str) -> str:
        message = _frame(NAMESPACE, _text(owner, 256), _text(account_subject, 1024), _text(media_id, 4096))
        return hmac.new(self._source_key, message, hashlib.sha256).hexdigest()
