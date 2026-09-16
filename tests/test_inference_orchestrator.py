"""Isolated tests with fake credentials, synthetic input and local transports."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from tools.inference_orchestrator.client import Credential, InferenceClient, InferenceError, read_credential, retry_delay
from tools.inference_orchestrator.runner import JobStore, Limits, RateGate, allowed_path, process_lock, run_plan, validate_plan, validate_proposal
from tools.inference_orchestrator.__main__ import main, make_slices, output_directory


FAKE_KEY = "synthetic-only-never-a-real-key-123456"
MODEL = "synthetic/test-model"
BASE = "a" * 40


def proposal(task_id):
    return {"task_id": task_id, "summary": "Validate server permissions before reading an object.", "patches": [],
        "checks": ["Try a cross-household read and require denial."], "limitations": ["Suggestion only; not tested."]}


class Response(io.BytesIO):
    status = 200


class Transport:
    def __init__(self, response):
        self.response, self.calls = response, []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if isinstance(self.response, Exception):
            raise self.response
        return Response(self.response if isinstance(self.response, bytes) else json.dumps(self.response).encode())


def chat_response(value, finish_reason="stop", **message_fields):
    return {"choices": [{"finish_reason": finish_reason, "message": {"content": json.dumps(value), **message_fields}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30, "untrusted": "ignore"}}


class FakeClient:
    credential = Credential(FAKE_KEY)

    def __init__(self, errors=(), wait=0):
        self.errors = list(errors)
        self.wait = wait
        self.calls = []
        self.lock = threading.Lock()
        self.active, self.peak = 0, 0

    def catalog(self):
        return {"operation": "GET /models", "http_status": 200, "latency_ms": 1, "model_ids": [MODEL]}

    def complete_json(self, model, messages, *, max_tokens):
        task = json.loads(messages[1]["content"])
        with self.lock:
            self.calls.append(task["task_id"])
            error = self.errors.pop(0) if self.errors else None
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(self.wait)
            if error:
                raise error
            return proposal(task["task_id"]), {"model": model, "http_status": 200, "latency_ms": 1, "usage": {"total_tokens": 30}}
        finally:
            with self.lock:
                self.active -= 1


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_credential_formats_and_redacted_repr(self):
        values = [FAKE_KEY, "NVIDIA_API_KEY='" + FAKE_KEY + "'", "Authorization: Bearer " + FAKE_KEY, json.dumps({"api_key": FAKE_KEY})]
        for value in values:
            with self.subTest(format=value[:3]):
                path = self.root / "input.txt"
                path.write_text(value, encoding="utf-8-sig")
                key = read_credential(path)
                self.assertEqual(key.value, FAKE_KEY)
                self.assertNotIn(FAKE_KEY, repr(key))

    def test_invalid_credential_file_never_echoes_input(self):
        for value in ["", FAKE_KEY + "\nother-synthetic-key-1234567", "not a key " + FAKE_KEY, "x" * 65537, "{invalid", "[]"]:
            with self.subTest(size=len(value)):
                path = self.root / "input.txt"
                path.write_text(value)
                with self.assertRaises(InferenceError) as caught:
                    read_credential(path)
                self.assertEqual(str(caught.exception), "credential_read_or_format")
                self.assertNotIn(FAKE_KEY, str(caught.exception))

    def test_verified_request_protocol_and_usage_allowlist(self):
        transport = Transport(chat_response({"ok": True}))
        client = InferenceClient(Credential(FAKE_KEY), opener_factory=lambda: transport)
        value, observation = client.complete_json(MODEL, [{"role": "user", "content": "synthetic"}], max_tokens=64)
        req, timeout = transport.calls[0]
        self.assertEqual(req.full_url, "https://inference-api.nvidia.com/v1/chat/completions")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(timeout, 30)
        self.assertEqual(req.get_header("Authorization"), "Bearer " + FAKE_KEY)
        sent = json.loads(req.data)
        self.assertEqual(sent["max_tokens"], 64)
        self.assertFalse(sent["stream"])
        self.assertNotIn("tools", sent)
        self.assertEqual(value, {"ok": True})
        self.assertEqual(set(observation["usage"]), {"prompt_tokens", "completion_tokens", "total_tokens"})

    def test_secrets_in_prompt_or_response_rejected(self):
        transport = Transport(chat_response({"text": FAKE_KEY}))
        client = InferenceClient(Credential(FAKE_KEY), opener_factory=lambda: transport)
        with self.assertRaisesRegex(InferenceError, "credential_in_content"):
            client.complete_json(MODEL, [{"role": "user", "content": FAKE_KEY}])
        self.assertEqual(len(transport.calls), 0)
        with self.assertRaisesRegex(InferenceError, "credential_in_content"):
            client.complete_json(MODEL, [{"role": "user", "content": "synthetic"}])

    def test_json_escaped_credential_echo_is_rejected_before_catalog_output(self):
        escaped = "".join("\\u%04x" % ord(char) for char in FAKE_KEY)
        response = ('{"data":[{"id":"' + escaped + '"}]}').encode()
        self.assertNotIn(FAKE_KEY.encode(), response)
        client = InferenceClient(Credential(FAKE_KEY), opener_factory=lambda: Transport(response))
        with self.assertRaisesRegex(InferenceError, "credential_in_content"):
            client.catalog()
        nested = chat_response({})
        nested["choices"][0]["message"]["content"] = '{"echo":"' + escaped + '"}'
        client = InferenceClient(Credential(FAKE_KEY), opener_factory=lambda: Transport(nested))
        with self.assertRaisesRegex(InferenceError, "credential_in_content"):
            client.complete_json(MODEL, [{"role": "user", "content": "synthetic"}])

    def test_http_error_body_headers_and_exception_are_not_exposed(self):
        error = HTTPError("https://ignored.invalid/" + FAKE_KEY, 429, FAKE_KEY, {"Retry-After": "7"}, io.BytesIO(FAKE_KEY.encode()))
        client = InferenceClient(Credential(FAKE_KEY), opener_factory=lambda: Transport(error))
        with self.assertRaises(InferenceError) as caught:
            client.catalog()
        self.assertEqual(str(caught.exception), "http_error")
        self.assertEqual(caught.exception.status, 429)
        self.assertEqual(caught.exception.retry_after, 7)
        self.assertTrue(caught.exception.retryable)

    def test_timeout_network_and_invalid_json_are_sanitized(self):
        for response, code in [(TimeoutError(FAKE_KEY), "timeout"), (URLError(FAKE_KEY), "transport_error"), (b"invalid-" + FAKE_KEY.encode(), "credential_in_content"), (b"{not json", "invalid_response")]:
            client = InferenceClient(Credential(FAKE_KEY), opener_factory=lambda: Transport(response))
            with self.subTest(code=code), self.assertRaisesRegex(InferenceError, code):
                client.catalog()

    def test_response_limit_and_invalid_model_output(self):
        cases = [(b"x" * 250001, "response_too_large"), (chat_response({}, "length"), "invalid_model_output"),
            (chat_response({}, tool_calls=[{"function": {"name": "shell"}}]), "invalid_model_output"),
            (chat_response({}, refusal="declined"), "invalid_model_output"),
            ({"choices": []}, "invalid_model_output"), (chat_response([1, 2]), "invalid_model_output")]
        for response, code in cases:
            client = InferenceClient(Credential(FAKE_KEY), opener_factory=lambda: Transport(response))
            with self.subTest(code=code), self.assertRaisesRegex(InferenceError, code):
                client.complete_json(MODEL, [{"role": "user", "content": "synthetic"}])

    def test_live_catalog_shape_validated(self):
        for data in [[], [{"id": MODEL}, {"id": MODEL}], [{"id": "unsafe\nheader"}], [{"id": 1}], [None]]:
            client = InferenceClient(Credential(FAKE_KEY), opener_factory=lambda: Transport({"data": data}))
            with self.subTest(data=data), self.assertRaisesRegex(InferenceError, "invalid_catalog"):
                client.catalog()
        client = InferenceClient(Credential(FAKE_KEY), opener_factory=lambda: Transport({"data": [{"id": MODEL}]}))
        self.assertEqual(client.catalog()["model_ids"], [MODEL])

    def test_redirect_handler_never_follows(self):
        from tools.inference_orchestrator.client import NoRedirect
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://other.invalid"))

    def test_retry_after_over_budget_is_not_retried_early(self):
        self.assertEqual(retry_delay("-2"), 0)
        self.assertEqual(retry_delay("nonsense"), 0)
        self.assertEqual(retry_delay("180"), 180)
        self.assertFalse(InferenceError("http_error", status=429, retry_after=180).retryable)


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan = make_slices(MODEL, BASE, 3)

    def test_root_plan_reservations_and_no_shell_fields(self):
        plan = make_slices(MODEL, BASE, 24)
        self.assertEqual(len(plan["tasks"]), 24)
        self.assertEqual(len({t["branch"] for t in plan["tasks"]}), 24)
        self.assertTrue(all(t["allowed_paths"] == [] for t in plan["tasks"]))
        for mutate in [lambda p: p["tasks"][0].update(command="shell"), lambda p: p["tasks"][0].update(branch="main"),
                lambda p: p["tasks"][0].update(worktree_name="../main"), lambda p: p["tasks"].append(p["tasks"][0]),
                lambda p: p.update(data_classification="personal_finance")]:
            modified = deepcopy(self.plan)
            mutate(modified)
            with self.assertRaises(InferenceError):
                validate_plan(modified)

    def test_paths_reject_traversal_hidden_and_secret_targets(self):
        for value in ["../app.py", "/tmp/app.py", "C:/app.py", ".env", ".git/config", "a/../app.py", "a//b", "a/./b", "secret.txt", "credentials.json", "key.pem", "a\\b.py"]:
            with self.subTest(value=value):
                self.assertFalse(allowed_path(value))
        self.assertTrue(allowed_path("tests/test_example.py"))

    def test_proposal_schema_rejects_actions_and_hidden_patch_targets(self):
        task = {**self.plan["tasks"][0], "allowed_paths": ["tests/example.py"]}
        value = proposal(task["id"])
        value["patches"] = [{"path": "tests/example.py", "diff": "--- /dev/null\n+++ b/tests/example.py\n@@ -0,0 +1 @@\n+x=1\n"}]
        self.assertEqual(validate_proposal(value, task), value)
        for mutate in [lambda v: v.update(shell="delete"), lambda v: v.update(task_id="other"),
                lambda v: v["patches"][0].update(path="app.py"),
                lambda v: v["patches"][0].update(diff="--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n+x")]:
            modified = deepcopy(value)
            mutate(modified)
            with self.assertRaises(InferenceError):
                validate_proposal(modified, task)

    def test_success_outputs_are_unreviewed_and_resuming_is_idempotent(self):
        client = FakeClient()
        with patch.object(RateGate, "wait"):
            first = run_plan(client, self.plan, self.root, Limits(workers=2))
            second = run_plan(client, self.plan, self.root, Limits(workers=2))
        self.assertEqual(first["state_counts"]["succeeded"], 3)
        self.assertEqual(first["request_attempts_this_run"], 3)
        self.assertEqual(second["request_attempts_this_run"], 0)
        self.assertEqual(second["total_recorded_request_attempts"], 3)
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(second["observed_max_concurrency"], 0)
        self.assertEqual(len(list((self.root / "runs").glob("*.json"))), 2)
        self.assertNotEqual(first["run_id"], second["run_id"])
        result = json.loads((self.root / "proposals" / (self.plan["tasks"][0]["id"] + ".json")).read_text())
        self.assertEqual(result["review_status"], "untrusted_unreviewed_proposal")
        self.assertFalse(result["applied"])
        self.assertFalse(result["tests_executed"])
        self.assertNotIn(FAKE_KEY, (self.root / "summary.json").read_text())

    def test_worker_and_observed_concurrency_limits(self):
        client = FakeClient(wait=0.04)
        with patch.object(RateGate, "wait"):
            result = run_plan(client, self.plan, self.root, Limits(workers=2))
        self.assertEqual(result["observed_max_concurrency"], client.peak)
        self.assertEqual(client.peak, 2)
        for limits in [{"workers": 25}, {"workers": 0}, {"requests_per_second": 9}, {"max_attempts": 4}, {"max_tokens": 3000}]:
            with self.assertRaises(InferenceError):
                Limits(**limits)

    def test_rate_gate_spaces_requests(self):
        gate = RateGate(5)
        start = time.monotonic()
        gate.wait()
        gate.wait()
        self.assertGreaterEqual(time.monotonic() - start, 0.18)

    def test_cancellation_stops_waiting_requests(self):
        stop = threading.Event()
        gate = RateGate(1)
        stop.set()
        self.assertFalse(gate.wait(stop))

    def test_interrupted_generation_stays_uncertain(self):
        client = FakeClient([KeyboardInterrupt()])
        result = run_plan(client, make_slices(MODEL, BASE, 1), self.root, Limits())
        self.assertTrue(result["interrupted"])
        self.assertEqual(result["state_counts"]["uncertain"], 1)
        self.assertEqual(len(client.calls), 1)

    def test_global_cooldown_and_bounded_retry(self):
        client = FakeClient([InferenceError("http_error", status=429, retry_after=3)])
        plan = make_slices(MODEL, BASE, 1)
        with patch.object(RateGate, "wait"), patch.object(RateGate, "cooldown") as cooldown:
            result = run_plan(client, plan, self.root, Limits(workers=1, max_attempts=2))
        self.assertGreaterEqual(cooldown.call_args.args[0], 3)
        self.assertEqual(result["state_counts"]["succeeded"], 1)
        self.assertEqual(result["total_recorded_request_attempts"], 2)

    def test_terminal_errors_never_retry(self):
        for code, status, state in [("http_error", 401, "failed"), ("invalid_model_output", None, "failed"),
                ("timeout", None, "uncertain"), ("transport_error", None, "uncertain")]:
            with self.subTest(code=code):
                client = FakeClient([InferenceError(code, status=status)])
                with patch.object(RateGate, "wait"):
                    result = run_plan(client, make_slices(MODEL, BASE, 1), self.root / (code + str(status)), Limits())
                self.assertEqual(result["state_counts"][state], 1)
                self.assertEqual(len(client.calls), 1)

    def test_attempt_cap_and_plan_change(self):
        client = FakeClient([InferenceError("http_error", status=503)] * 4)
        plan = make_slices(MODEL, BASE, 1)
        with patch.object(RateGate, "wait"), patch.object(RateGate, "cooldown"):
            result = run_plan(client, plan, self.root, Limits(max_attempts=2))
        self.assertEqual(result["state_counts"]["failed"], 1)
        self.assertEqual(len(client.calls), 2)
        changed = deepcopy(plan)
        changed["tasks"][0]["context"] += " changed"
        with self.assertRaisesRegex(InferenceError, "plan_changed"):
            run_plan(client, changed, self.root, Limits())

    def test_crash_recovery_requires_explicit_requeue_within_budget(self):
        plan = make_slices(MODEL, BASE, 1)
        task_id = plan["tasks"][0]["id"]
        store = JobStore(self.root, plan)
        attempt = store.start(task_id, 2)
        self.assertIsNotNone(attempt)
        store.close()
        client = FakeClient()
        result = run_plan(client, plan, self.root, Limits())
        self.assertEqual(result["state_counts"]["uncertain"], 1)
        self.assertEqual(len(client.calls), 0)
        store = JobStore(self.root, plan)
        store.requeue(task_id, 2)
        store.close()
        result = run_plan(client, plan, self.root, Limits())
        self.assertEqual(result["state_counts"]["succeeded"], 1)
        self.assertEqual(result["total_recorded_request_attempts"], 2)

    def test_model_missing_from_catalog_fails_before_requests(self):
        client = FakeClient()
        client.catalog = lambda: {"model_ids": []}
        with self.assertRaisesRegex(InferenceError, "model_not_in_live_catalog"):
            run_plan(client, self.plan, self.root, Limits())
        self.assertEqual(client.calls, [])

    def test_no_secret_persisted_when_plan_contains_credential(self):
        plan = deepcopy(self.plan)
        plan["tasks"][0]["context"] += FAKE_KEY
        with self.assertRaisesRegex(InferenceError, "credential_in_content"):
            run_plan(FakeClient(), plan, self.root / "no-state", Limits())
        self.assertFalse((self.root / "no-state").exists())

    def test_process_lock_rejects_a_second_runner(self):
        with process_lock(self.root / "run.lock"):
            with self.assertRaisesRegex(InferenceError, "run_already_active"):
                with process_lock(self.root / "run.lock"):
                    self.fail("second lock acquired")

    def test_cli_outputs_are_ignored_and_errors_sanitized(self):
        with self.assertRaisesRegex(InferenceError, "output_must_be_in_ignored_results"):
            output_directory(self.root)
        with patch("tools.inference_orchestrator.__main__.OUTPUT_ROOT", self.root), redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()) as stderr:
            code = main(["catalog", "--key-file", str(self.root / FAKE_KEY), "--output-dir", str(self.root / "result")])
        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertNotIn(FAKE_KEY, stderr.getvalue())
        self.assertEqual(json.loads(stderr.getvalue())["error"], "credential_read_or_format")


if __name__ == "__main__":
    unittest.main()
