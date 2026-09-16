"""python -m tools.inference_orchestrator --help"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .client import InferenceClient, InferenceError, read_credential
from .runner import JobStore, Limits, atomic_json, process_lock, run_plan, validate_plan


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = ROOT / "test-results" / "inference-orchestrator"
SLICES = [
    ("household-isolation", "Server-side household isolation for every route, file and background job."),
    ("private-spaces", "Object-level personal versus explicitly shared visibility, including financial records and media."),
    ("membership-revocation", "Invite, join, leave and role changes; revoke member access immediately in background jobs and browser sessions."),
    ("ai-preview-confirm", "AI request to validated preview, explicit confirmation, idempotent execution receipt; suggestions never count as executed."),
    ("ai-failure-recovery", "AI timeout, throttling, invalid structured output and unavailable model recovery without losing the user's draft."),
    ("prompt-injection", "Treat imported files, webpages and media metadata as untrusted data; server-side tool authorization."),
    ("travel-timezones", "Multi-city travel with local dates and IANA time zones, overnight flights and exclusive hotel checkout dates."),
    ("travel-reschedule", "Reschedule travel and identify affected tasks, purchases and calendar events while preserving independent edits."),
    ("travel-task-generation", "Preview, assign and persist travel preparation tasks and purchases; reruns must not duplicate work."),
    ("calendar-idempotency", "Authorized calendar create/update sync with durable jobs, stable identities, uncertain creation and conflict handling."),
    ("recurring-chores", "Recurring household tasks with assignees, dependencies, deadlines, completion and exception handling."),
    ("purchase-lifecycle", "Purchase need, list, budget, owner, order, delivery, refund and expense linkage without double counting."),
    ("inventory-replenishment", "Check household stock and in-flight orders before recommending replenishment; useful manual entry fallback."),
    ("bill-import-preview", "CSV/XLSX import preview, explicit field mapping, exact monetary arithmetic and row-level errors."),
    ("bill-deduplication", "Repeated imports and overlapping exports remain idempotent with durable provenance and content-change conflicts."),
    ("refund-reconciliation", "Distinguish spending, transfers, card repayments and refunds; match orders to payments without duplicate expenses."),
    ("budget-coverage", "Show budget and trip totals with source freshness, incomplete coverage and currency boundaries clearly."),
    ("asset-valuations", "Manual/imported asset accounts, holdings and liabilities with original currency, valuation dates and unknown values."),
    ("media-source-auth", "Connect one actually authorized media source; manual import alternative and accurate connection/coverage state."),
    ("media-deduplication", "Preserve original media source, index duplicates, suggest travel links and require confirmation before sharing."),
    ("travel-map-privacy", "Distinguish visited, planned and wishlist locations; blur sensitive places and never infer a visit without confirmation."),
    ("tv-access-scope", "Pair and revoke read-only display devices; allowlisted media only, excluding private calendars and finance."),
    ("backup-recovery", "Durable sync queues, household-scoped data export, consistent backups and verified recovery with expired sessions."),
    ("accessible-feedback", "Chinese-first phone/desktop/TV flows with loading, empty, error, stale and offline feedback plus keyboard support."),
]


def output_directory(value):
    path = Path(value).resolve()
    root = OUTPUT_ROOT.absolute()
    if root.resolve() != root:
        raise InferenceError("results_root_must_not_redirect")
    try:
        relative = path.relative_to(root)
    except ValueError:
        raise InferenceError("output_must_be_in_ignored_results") from None
    if not relative.parts:
        raise InferenceError("choose_named_run_directory")
    return path


def read_plan(path):
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(1000001)
        if len(raw) > 1000000:
            raise InferenceError("plan_too_large")
        return validate_plan(json.loads(raw.decode("utf-8-sig")))
    except (OSError, UnicodeError, ValueError, TypeError):
        raise InferenceError("plan_read_or_format") from None


def make_slices(model, base, count):
    if not 1 <= count <= len(SLICES):
        raise InferenceError("invalid_slice_count")
    tasks = []
    for name, requirement in SLICES[:count]:
        tasks.append({"id": name, "branch": "codex/inference-" + name, "worktree_name": "inference-" + name,
            "instruction": "Assess this requirement as an independent development slice. Recommend a small verifiable implementation increment and meaningful acceptance checks. Return patches=[]; no source files are provided.",
            "context": "Generic family management application using Flask, vanilla JavaScript and per-household SQLite. Existing preview/confirm and permission boundaries must be retained. This is sanitized requirements context, not a claim about existing implementation. Requirement: " + requirement,
            "allowed_paths": []})
    return validate_plan({"version": 1, "base_commit": base, "model": model, "data_classification": "synthetic_or_approved_source", "tasks": tasks})


def parser():
    result = argparse.ArgumentParser(description="Bounded development proposals only; never applies patches or creates Git refs.")
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("catalog", "probe", "run"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--key-file", required=True, help="Server-side credential file; its contents are never printed.")
        cmd.add_argument("--output-dir", required=True, help="Named directory below test-results/inference-orchestrator/.")
        cmd.add_argument("--timeout", type=float, default=30)
        if name == "probe":
            cmd.add_argument("--model", required=True)
        if name == "run":
            cmd.add_argument("--plan", required=True)
            cmd.add_argument("--workers", type=int, default=2)
            cmd.add_argument("--requests-per-second", type=float, default=1)
            cmd.add_argument("--max-tokens", type=int, default=700)
            cmd.add_argument("--max-attempts", type=int, default=2)
    cmd = commands.add_parser("slices-plan", help="Prepare sanitized requirement slices for root review; sends no requests.")
    cmd.add_argument("--output-dir", required=True)
    cmd.add_argument("--model", required=True, help="Exact ID already observed in the live catalog.")
    cmd.add_argument("--base", required=True)
    cmd.add_argument("--count", type=int, default=24)
    for name in ("status", "requeue"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--output-dir", required=True)
        cmd.add_argument("--plan", required=True)
        if name == "requeue":
            cmd.add_argument("--task-id", required=True)
            cmd.add_argument("--max-attempts", type=int, choices=(1, 2, 3), default=2)
            cmd.add_argument("--acknowledge-possible-duplicate-generation", action="store_true", required=True)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        directory = output_directory(args.output_dir)
        if args.command == "slices-plan":
            plan = make_slices(args.model, args.base, args.count)
            if (directory / "plan.json").exists():
                raise InferenceError("plan_already_exists")
            atomic_json(directory / "plan.json", plan)
            result = {"planned_jobs": len(plan["tasks"]), "requests_sent": 0, "git_refs_created": 0}
        elif args.command in {"status", "requeue"}:
            plan = read_plan(args.plan)
            with process_lock(directory / "run.lock"):
                if not (directory / "jobs.sqlite3").exists():
                    raise InferenceError("state_not_found")
                store = JobStore(directory, plan)
                try:
                    store.recover()
                    if args.command == "requeue":
                        store.requeue(args.task_id, args.max_attempts)
                    result = store.summary()
                finally:
                    store.close()
        else:
            credential = read_credential(args.key_file)
            client = InferenceClient(credential, timeout=args.timeout)
            if args.command == "catalog":
                result = client.catalog()
                with process_lock(directory / "run.lock"):
                    atomic_json(directory / "catalog.json", result)
            elif args.command == "probe":
                with process_lock(directory / "run.lock"):
                    catalog = client.catalog()
                    if args.model not in catalog["model_ids"]:
                        raise InferenceError("model_not_in_live_catalog")
                    value, observation = client.complete_json(args.model, [
                        {"role": "system", "content": "Return one JSON object only. No tools or external information."},
                        {"role": "user", "content": 'Synthetic protocol check. Return exactly {"ok":true,"sum":5}.'},
                    ], max_tokens=64)
                    valid = value == {"ok": True, "sum": 5} and type(value.get("sum")) is int and value.get("ok") is True
                    result = {**observation, "json_validated": valid, "catalog_model_count": len(catalog["model_ids"])}
                    atomic_json(directory / "probe.json", result)
                    if not valid:
                        raise InferenceError("probe_output_mismatch")
            else:
                result = run_plan(client, read_plan(args.plan), directory, Limits(args.workers, args.requests_per_second, args.max_tokens, args.max_attempts))
        print(json.dumps(result, ensure_ascii=False))
        if args.command == "run" and any(result["state_counts"][s] for s in ("queued", "running", "failed", "uncertain")):
            return 1
        return 0
    except InferenceError as error:
        print(json.dumps({"error": error.code, "http_status": error.status}), file=sys.stderr)
        return 2
    except (Exception, KeyboardInterrupt):
        # CLI must never expose a credential through a traceback or repr.
        print(json.dumps({"error": "interrupted_or_local_error"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
