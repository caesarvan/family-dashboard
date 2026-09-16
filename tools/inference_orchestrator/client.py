"""Small, bounded client for the designated NVIDIA gateway.

No response bodies, request bodies, headers or exception strings are logged.
Only the two verified HTTP operations are exposed. Credentials never serialize.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


BASE_URL = "https://inference-api.nvidia.com/v1"
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./:-]{0,199}\Z")
KEY = re.compile(r"[A-Za-z0-9_.-]{20,4096}\Z")


class InferenceError(Exception):
    """Fixed safe code only. Never attach provider body, URL or exception text."""

    def __init__(self, code, *, status=None, retry_after=0):
        super().__init__(code)
        self.code, self.status, self.retry_after = code, status, retry_after

    @property
    def retryable(self):
        return self.status in {429, 500, 502, 503, 504} and self.retry_after <= 120


@dataclass(frozen=True)
class Credential:
    value: str = field(repr=False)

    def reject_leak(self, value):
        if self.value in value:
            raise InferenceError("credential_in_content")


def read_credential(path):
    """Accept one raw token, KEY=value, JSON api_key, or Bearer header.

    Ambiguity fails closed. The key path is supplied by the operator and is
    never copied into plans, databases, reports, errors or model messages.
    """
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError
        text = raw.decode("utf-8-sig").strip()
        candidates = []
        if text.startswith("{"):
            obj = json.loads(text)
            if not isinstance(obj, dict):
                raise ValueError
            candidates = [obj[k] for k in ("api_key", "API_KEY", "NVIDIA_API_KEY", "INFERENCE_API_KEY", "OPENAI_API_KEY") if k in obj]
        else:
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                match = re.fullmatch(r"(?:export\s+)?(?:NVIDIA_API_KEY|INFERENCE_API_KEY|OPENAI_API_KEY|API_KEY|api_key)\s*[:=]\s*['\"]?([^\s'\"]+)['\"]?", line)
                bearer = re.fullmatch(r"(?:Authorization:\s*)?Bearer\s+([A-Za-z0-9_.-]{20,4096})", line, re.I)
                if match:
                    candidates.append(match[1])
                elif bearer:
                    candidates.append(bearer[1])
                elif KEY.fullmatch(line):
                    candidates.append(line)
                else:
                    raise ValueError
        if not candidates or any(not isinstance(item, str) or not KEY.fullmatch(item) for item in candidates):
            raise ValueError
        if len(set(candidates)) != 1:
            raise ValueError
        return Credential(candidates[0])
    except (OSError, UnicodeError, ValueError, TypeError):
        raise InferenceError("credential_read_or_format") from None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def retry_delay(value):
    """A cooldown over 120 seconds is terminal for this bounded invocation."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return 0.0
    return max(0.0, min(seconds, 86400.0))


class InferenceClient:
    def __init__(self, credential, *, timeout=30.0, opener_factory=None):
        if not 1 <= timeout <= 60:
            raise InferenceError("invalid_timeout")
        self.credential = credential
        self.timeout = timeout
        # An opener per request avoids sharing transport state between workers.
        self.opener_factory = opener_factory or (lambda: build_opener(NoRedirect()))

    def _request(self, path, payload=None, *, limit=250000):
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if data is not None:
            self.credential.reject_leak(data.decode("utf-8"))
        request = Request(BASE_URL + path, data=data, headers={
            "Authorization": "Bearer " + self.credential.value,
            "Accept": "application/json", "Content-Type": "application/json",
        }, method="GET" if payload is None else "POST")
        started = time.monotonic()
        try:
            with self.opener_factory().open(request, timeout=self.timeout) as response:
                if response.status != 200:
                    raise InferenceError("unexpected_http_status", status=response.status)
                chunks, size = [], 0
                read = getattr(response, "read1", response.read)
                while True:
                    if time.monotonic() - started > self.timeout:
                        raise InferenceError("timeout")
                    chunk = read(min(65536, limit + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > limit:
                        raise InferenceError("response_too_large")
                raw = b"".join(chunks).decode("utf-8")
            self.credential.reject_leak(raw)
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError
            # JSON escapes must not let a provider echo bypass the raw check.
            self.credential.reject_leak(json.dumps(result, ensure_ascii=False))
            return result, round((time.monotonic() - started) * 1000)
        except HTTPError as error:
            status = error.code
            delay = retry_delay(error.headers.get("Retry-After")) if error.headers else 0
            error.close()
            raise InferenceError("http_error", status=status, retry_after=delay) from None
        except (TimeoutError,):
            raise InferenceError("timeout") from None
        except (URLError, OSError):
            raise InferenceError("transport_error") from None
        except (ValueError, UnicodeError, TypeError, KeyError):
            raise InferenceError("invalid_response") from None

    def catalog(self):
        result, latency = self._request("/models", limit=2000000)
        data = result.get("data")
        if not isinstance(data, list) or not data or len(data) > 5000:
            raise InferenceError("invalid_catalog")
        ids = []
        for item in data:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not MODEL_ID.fullmatch(item["id"]):
                raise InferenceError("invalid_catalog")
            ids.append(item["id"])
        if len(ids) != len(set(ids)):
            raise InferenceError("invalid_catalog")
        return {"operation": "GET /models", "http_status": 200, "latency_ms": latency, "model_ids": ids}

    def complete_json(self, model, messages, *, max_tokens=700):
        if not isinstance(model, str) or not MODEL_ID.fullmatch(model) or not 32 <= max_tokens <= 1500:
            raise InferenceError("invalid_request")
        if not isinstance(messages, list) or not 1 <= len(messages) <= 4 or any(
            not isinstance(m, dict) or set(m) != {"role", "content"}
            or m["role"] not in {"system", "user"} or not isinstance(m["content"], str)
            or len(m["content"]) > 20000 for m in messages
        ):
            raise InferenceError("invalid_request")
        result, latency = self._request("/chat/completions", {
            "model": model, "messages": messages, "max_tokens": max_tokens,
            "temperature": 0, "stream": False,
        })
        try:
            choices = result["choices"]
            if not isinstance(choices, list) or len(choices) != 1:
                raise ValueError
            choice = choices[0]
            message = choice["message"]
            if choice.get("finish_reason") != "stop" or message.get("tool_calls") or message.get("function_call") or message.get("refusal"):
                raise ValueError
            content = message["content"]
            if not isinstance(content, str) or len(content) > 80000:
                raise ValueError
            content = content.strip()
            if content.startswith("```json\n") and content.endswith("```"):
                content = content[8:-3].strip()
            obj = json.loads(content)
            if not isinstance(obj, dict):
                raise ValueError
            self.credential.reject_leak(json.dumps(obj, ensure_ascii=False))
            usage = result.get("usage", {})
            if not isinstance(usage, dict):
                usage = {}
            usage = {k: v for k, v in usage.items() if k in {"prompt_tokens", "completion_tokens", "total_tokens"} and type(v) is int and v >= 0}
            return obj, {"model": model, "operation": "POST /chat/completions", "http_status": 200, "latency_ms": latency, "usage": usage}
        except (ValueError, KeyError, TypeError, AttributeError):
            raise InferenceError("invalid_model_output") from None
