"""Bounded offline acceptance of two explicitly supplied real order files.

This opt-in CLI never runs under pytest collection. It exercises the real app
against a disposable database and emits only fixed messages and aggregate facts.
No source rows, values, identifiers, tokens, filenames or database are retained.
"""
from __future__ import annotations

import argparse
import asyncio  # Load Windows subprocess support before denying child processes.
import base64
from collections import Counter
from contextlib import closing, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import gc
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
FINANCE_TABLES = ('hub_transactions', 'hub_imports', 'hub_import_receipts',
                  'hub_budgets', 'hub_reconciliations')
PROTECTED_TABLES = ('private_finance', 'finance_baselines', 'finance_spending_observations',
                    'finance_spending_receipts', 'hub_budgets', 'hub_reconciliations', 'hub_investments')
BASE_URL = '/api/finance-hub'


class CheckFailed(Exception):
    pass


def need(condition, code):
    if not condition:
        raise CheckFailed(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def snapshot(path, tables=FINANCE_TABLES):
    with closing(sqlite3.connect(path)) as con:
        return {name: con.execute('SELECT * FROM "' + name + '" ORDER BY rowid').fetchall()
                for name in tables}


def protected(path):
    values = snapshot(path, PROTECTED_TABLES)
    with closing(sqlite3.connect(path)) as con:
        values['shared_finance'] = con.execute("SELECT * FROM settings WHERE id='finance'").fetchall()
    return values


def stored(path):
    with closing(sqlite3.connect(path)) as con:
        return {key: json.loads(raw) for key, raw in con.execute(
            'SELECT fingerprint,data FROM hub_transactions WHERE owner=?', ('member1',))}


def response(client, method, url, headers, payload=None):
    kwargs = {'headers': headers}
    if payload is not None:
        kwargs['json'] = payload
    result = client.open(url, method=method, **kwargs)
    need(result.status_code == 200, 'unexpected_http_status')
    need(isinstance(result.json, dict), 'invalid_response_shape')
    return result.json


def login(application):
    client = application.test_client()
    response(client, 'POST', '/api/login', {},
             {'username': 'member1', 'password': 'offline-order-fixture-password-one'})
    me = response(client, 'GET', '/api/me', {})
    return client, {'X-CSRF-Token': me['csrf']}


def read_all(client, headers, months):
    rows, calls = [], 0
    for month in sorted(months):
        first = response(client, 'GET', BASE_URL + '/transactions?month=' + month + '&pageSize=100', headers)
        calls += 1
        monthly = list(first['transactions'])
        for page in range(2, first['totalPages'] + 1):
            value = response(client, 'GET', BASE_URL + '/transactions?month=' + month
                + '&pageSize=100&page=' + str(page) + '&snapshot=' + first['snapshot'], headers)
            need(value['snapshot'] == first['snapshot'], 'pagination_snapshot_changed')
            monthly += value['transactions']
            calls += 1
        need(len(monthly) == first['transactionCount'], 'pagination_incomplete')
        rows += monthly
    need(len({row['id'] for row in rows}) == len(rows), 'duplicate_api_row')
    return rows, calls


def check_rows(shown, saved, accepted, payload):
    for row in shown['rows']:
        value = saved[row['fingerprint']]
        business = {key: child for key, child in row.items()
                    if key not in {'line', 'sourceLocation', 'duplicate', 'conflict'}}
        need(all(value.get(key) == child for key, child in business.items()), 'business_value_changed')
        expected = {'status': 'recorded', 'batchId': accepted['batchId'], 'source': payload['source'],
                    'kind': 'orders', 'fileName': payload['file']['name'],
                    'format': shown['fileInfo']['format'], 'sheet': shown['fileInfo'].get('sheet'),
                    **row['sourceLocation'], 'importedAt': accepted['confirmedAt']}
        need(value['provenance'] == expected, 'first_provenance_changed')
        need(value['visibility'] == 'private' and value['kind'] == 'orders', 'private_order_scope_changed')


def exercise(client, headers, database, source, raw, reference, item):
    file = {'name': 'private-order-sample.' + ('xlsx' if source == 'taobao' else 'csv'),
            'contentBase64': base64.b64encode(raw).decode('ascii'), 'encoding': 'auto'}
    before = snapshot(database)
    if source == 'taobao':
        discovery = response(client, 'POST', BASE_URL + '/imports/preview', headers,
                             {'source': source, 'kind': 'orders', 'file': file, 'inspectSheets': True})
        need(len(discovery['fileInfo']['sheets']) == 1, 'unexpected_worksheet_count')
        need(not discovery.get('previewToken'), 'discovery_issued_confirmation')
        file['sheet'] = discovery['fileInfo']['sheets'][0]
        need(snapshot(database) == before, 'discovery_wrote_finance')
        item['worksheetDiscoveryPassed'] = True
    payload = {'source': source, 'kind': 'orders', 'file': file}
    shown = response(client, 'POST', BASE_URL + '/imports/preview', headers, payload)
    need(snapshot(database) == before, 'preview_wrote_finance')
    need(shown['errorCount'] == 0 and shown['previewToken'], 'preview_not_confirmable')
    need(not shown['requiresAmountSelection'] and not shown['requiresSheetSelection']
         and not shown['requiresColumnSelection'], 'unresolved_file_selection')
    prior = reference['sheets'][0]
    need(len(shown['rows']) == prior['parsedRows'], 'historical_row_count_changed')
    need(shown['newCount'] == prior['newCount'] and shown['duplicateCount'] == 0
         and shown['conflictCount'] == 0, 'unexpected_initial_duplicates')
    need(dict(Counter(row['flow'] for row in shown['rows'])) == prior['flowCounts'], 'historical_flow_changed')
    grouped = [row for row in shown['rows'] if row.get('orderGroup', {}).get('format') == 'taobao-merged-v1']
    need(sum(len(row['orderItems']) for row in grouped) == prior['itemCount'], 'historical_item_count_changed')
    need(all(row['kind'] == 'orders' and row['flow'] in {'unknown', 'excluded'} for row in shown['rows']),
         'order_incorrectly_treated_as_payment')
    need(all(t['netSpendCents'] == 0 for t in shown['totals']), 'orders_counted_as_net_spend')
    item.update(parsedRows=len(shown['rows']), itemRows=sum(len(row['orderItems']) for row in grouped),
                flowCounts=dict(Counter(row['flow'] for row in shown['rows'])),
                currencyExplicitInOriginal=prior['currencyColumnPresent'], currencyIndependentlyConfirmed=False,
                previewNoWrites=True, previewErrorCount=0, originalStructureCountsMatchPrior=True)

    original_request = {**payload, 'previewToken': shown['previewToken'],
                        'requestId': sha((source + '-first-confirm').encode())}
    accepted = response(client, 'POST', BASE_URL + '/imports/confirm', headers, original_request)
    need(accepted['imported'] == len(shown['rows']) and accepted['duplicates'] == 0
         and accepted['conflicts'] == 0 and not accepted['replayed'], 'initial_confirm_counts')
    saved = stored(database)
    check_rows(shown, saved, accepted, payload)
    committed = snapshot(database)
    receipt = response(client, 'GET', BASE_URL + '/imports/results/' + original_request['requestId'], headers)
    replay = response(client, 'POST', BASE_URL + '/imports/confirm', headers, original_request)
    need(receipt == replay == {**accepted, 'replayed': True}, 'original_receipt_or_replay_changed')
    need(snapshot(database) == committed, 'original_replay_wrote_finance')
    item.update(confirmedRows=accepted['imported'], confirmedInDisposableDatabase=True,
                businessValuesPreserved=True, firstProvenancePreserved=True, receiptAndExactReplayPassed=True)

    repeated = response(client, 'POST', BASE_URL + '/imports/preview', headers, payload)
    need(snapshot(database) == committed, 'repeat_preview_wrote_finance')
    need(repeated['newCount'] == 0 and repeated['duplicateCount'] == len(shown['rows'])
         and repeated['conflictCount'] == 0, 'same_file_not_deduplicated')
    repeated_result = response(client, 'POST', BASE_URL + '/imports/confirm', headers,
        {**payload, 'previewToken': repeated['previewToken'], 'requestId': sha((source + '-reimport').encode())})
    need(repeated_result['imported'] == 0 and repeated_result['duplicates'] == len(shown['rows'])
         and repeated_result['conflicts'] == 0 and repeated_result['batchId'] is None, 'reimport_inserted_rows')
    after_repeat = snapshot(database)
    need(after_repeat['hub_transactions'] == committed['hub_transactions']
         and after_repeat['hub_imports'] == committed['hub_imports'], 'reimport_changed_original_rows_or_batch')
    need(len(after_repeat['hub_import_receipts']) == len(committed['hub_import_receipts']) + 1, 'missing_reimport_receipt')
    need(stored(database) == saved, 'reimport_changed_first_provenance')
    months = {row['date'][:7] for row in saved.values()}
    actual, calls = read_all(client, headers, months)
    need(len(actual) == len(saved), 'api_readback_incomplete')
    actual_by_fingerprint = {row['fingerprint']: row for row in actual}
    for fingerprint, value in saved.items():
        need(all(actual_by_fingerprint[fingerprint].get(key) == child for key, child in value.items()),
             'api_readback_changed_business_or_provenance')
    item.update(reimportedRows=0, duplicateRows=repeated_result['duplicates'], conflictRows=0,
                sameFileDeduplicationPassed=True, completePaginatedReadbackPassed=True,
                readbackPageCalls=calls, firstSourceStableAfterReimport=True)
    return months


class DiscardOutput(io.TextIOBase):
    def write(self, text):
        return len(text)


def run(args):
    need(sys.dont_write_bytecode and not sys.flags.optimize, 'python_B_without_optimization_required')
    output = args.output.absolute()
    allowed_output = ROOT / 'test-results'
    need('..' not in output.parts and output.is_relative_to(allowed_output)
         and not output.exists(), 'new_ignored_output_required')
    for path in (output.parent, *output.parent.parents):
        need(not path.is_symlink() and not path.is_junction(), 'linked_output_path')
    paths = {'taobao': args.taobao.absolute(), 'pinduoduo': args.pinduoduo.absolute()}
    need(paths['taobao'].suffix.lower() == '.xlsx' and paths['pinduoduo'].suffix.lower() == '.csv', 'unexpected_input_format')
    for path in (*paths.values(), args.compatibility_index.absolute()):
        need(path.is_file() and not path.is_symlink() and '..' not in path.parts, 'regular_input_required')
        for parent in path.parents:
            need(not parent.is_symlink() and not parent.is_junction(), 'linked_input_parent')
        need(not path.is_relative_to(ROOT), 'private_inputs_must_remain_outside_repository')
    reference_raw = args.compatibility_index.read_bytes()
    need(sha(reference_raw) == args.compatibility_index_sha256, 'compatibility_index_changed')
    reference = json.loads(reference_raw)
    need(reference['completed'] and not reference['confirmationCalled'] and reference['sourceUnchanged'],
         'unsupported_historical_reference')
    references = {item['source']: item for item in reference['files']}
    need(set(references) == set(paths), 'historical_source_set_changed')
    raw_inputs = {}
    for source, path in paths.items():
        need(path.stat().st_size <= 2 * 1024 * 1024, 'source_file_too_large')
        raw_inputs[source] = path.read_bytes()
        need(sha(raw_inputs[source]) == references[source]['sha256Before'] == references[source]['sha256After'],
             'input_differs_from_reviewed_real_sample')
    git = lambda *values: subprocess.check_output(['git', '-C', str(ROOT), *values]).decode().strip()
    head, tree = git('rev-parse', 'HEAD'), git('rev-parse', 'HEAD^{tree}')
    need(head == args.source_head, 'source_head_changed')
    names = [name for name in git('ls-files', '*.py', 'requirements.txt', 'pytest.ini').splitlines() if name]
    names = sorted(set(names) | {Path(__file__).relative_to(ROOT).as_posix()})
    before_source = {name: sha((ROOT / name).read_bytes()) for name in names}
    output.mkdir(parents=True)
    report = dict(schemaVersion=1, kind='real-order-files-disposable-api-acceptance', completed=False,
        sourceHead=head, sourceTree=tree, startedAt=datetime.now(timezone.utc).isoformat(),
        compatibilityIndexSha256=sha(reference_raw), sourceHashesBefore=before_source,
        files=[{'source': source, 'format': paths[source].suffix[1:], 'bytes': len(raw),
                'sha256Before': sha(raw), 'completed': False} for source, raw in raw_inputs.items()],
        networkAttempts=0, childProcessAttempts=0, productionWrites=0, uploads=0,
        inputData='real_files_exact_bytes', rawValuesRetainedInReport=False,
        databaseRetained=False, originalFilesModified=False,
        fullScenarioBComplete=False, limitations=[
            'Real original order bytes were accepted only into a disposable local app, not a production or user financial ledger.',
            'Both sources lack an explicit currency column; parser default currency is not independently confirmed.',
            'Order rows remain unknown or excluded; no actual payment or refund is inferred from order status.',
            'Payment imports, independent refund linkage and budget acceptance are not exercised in this bounded order-only run.',
            'No browser UI, screenshots, archive decryption, mailbox, credentials or remote platform verification.'
        ])
    temporary = None
    old_logging = logging.root.manager.disable
    def network_denied(*_args, **_kwargs):
        report['networkAttempts'] += 1
        raise CheckFailed('network_forbidden')
    def process_denied(*_args, **_kwargs):
        report['childProcessAttempts'] += 1
        raise CheckFailed('child_process_forbidden')
    environment = {name: value for name, value in os.environ.items()
                   if name.upper() in {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'COMSPEC', 'PATHEXT'}}
    try:
        with patch.dict(os.environ, environment, clear=True), patch.object(socket.socket, 'connect', network_denied), \
             patch.object(socket.socket, 'connect_ex', network_denied), patch.object(socket, 'create_connection', network_denied), \
             patch.object(socket, 'getaddrinfo', network_denied), patch.object(subprocess, 'Popen', process_denied), \
             patch.object(os, 'system', process_denied), redirect_stdout(DiscardOutput()), redirect_stderr(DiscardOutput()):
            logging.disable(logging.CRITICAL)
            sys.path.insert(0, str(ROOT))
            from app import create_app
            temporary = tempfile.TemporaryDirectory(prefix='private-disposable-', dir=output)
            temp_path = Path(temporary.name).resolve()
            need(temp_path.is_relative_to(output.resolve()), 'temporary_path_outside_output')
            config = {'TESTING': True, 'SECRET_KEY': 'offline-order-fixture-secret', 'DATA_DIR': str(temp_path),
                'SESSION_COOKIE_SECURE': False, 'MEMBER1_PASSWORD': 'offline-order-fixture-password-one',
                'MEMBER2_PASSWORD': 'offline-order-fixture-password-two', 'OPENAI_API_KEY': '', 'NVIDIA_API_KEY': '',
                'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': '', 'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': ''}
            application = create_app(config)
            database = temp_path / 'household.sqlite3'
            client, headers = login(application)
            untouched = protected(database)
            months = set()
            for item in report['files']:
                source = item['source']
                raw = raw_inputs[source]
                months |= exercise(client, headers, database, source, raw, references[source], item)
                need(protected(database) == untouched, 'unrelated_finance_changed')
                item['completed'] = True
            final_snapshot = snapshot(database)
            restarted = create_app(config)
            restarted_client, restarted_headers = login(restarted)
            need(snapshot(database) == final_snapshot, 'restart_changed_saved_finance')
            rows, _calls = read_all(restarted_client, restarted_headers, months)
            saved = stored(database)
            need(len(rows) == len(saved), 'restart_readback_incomplete')
            by_fingerprint = {row['fingerprint']: row for row in rows}
            need(all(all(by_fingerprint[key].get(field) == value for field, value in item.items())
                     for key, item in saved.items()), 'restart_readback_changed_values')
            need(protected(database) == untouched, 'protected_finance_changed_after_restart')
            report.update(restartReadbackPassed=True, unrelatedFinanceUnchanged=True,
                          finalOrderRows=len(saved), paymentsOrRefundsCreated=0,
                          sourceProvenanceCheckedForEveryRow=True, completed=True)
    except Exception as exc:
        report.update(completed=False, failureType=type(exc).__name__,
                      failureCode=str(exc) if isinstance(exc, CheckFailed) else 'private_infrastructure_detail_withheld')
    finally:
        logging.disable(old_logging)
        gc.collect()
        if temporary is not None:
            try:
                need(Path(temporary.name).resolve().is_relative_to(output.resolve()), 'unsafe_cleanup_target')
                temporary.cleanup()
                report['privateTemporaryDirectoryRemoved'] = not Path(temporary.name).exists()
            except Exception:
                report.update(completed=False, privateTemporaryDirectoryRemoved=False,
                              databaseRetained=True, cleanupFailure='private_cleanup_failed')
        for item in report['files']:
            item['sha256After'] = sha(paths[item['source']].read_bytes())
            item['originalUnchanged'] = item['sha256Before'] == item['sha256After']
            if not item['originalUnchanged']:
                report['completed'] = False
                report['originalFilesModified'] = True
        report['sourceHashesAfter'] = {name: sha((ROOT / name).read_bytes()) for name in names}
        report['sourceUnchanged'] = report['sourceHashesAfter'] == before_source
        report['compatibilityIndexUnchanged'] = sha(args.compatibility_index.read_bytes()) == sha(reference_raw)
        report['completed'] = bool(report['completed'] and report['sourceUnchanged']
            and report['compatibilityIndexUnchanged'] and not report['networkAttempts'] and not report['childProcessAttempts'])
        report['finishedAt'] = datetime.now(timezone.utc).isoformat()
        with (output / 'result.json').open('xb') as stream:
            stream.write(encoded(report))
    print(json.dumps({'completed': report['completed'], 'files': [
        {key: item[key] for key in ('source', 'completed', 'parsedRows', 'confirmedRows', 'duplicateRows',
                                   'currencyExplicitInOriginal', 'originalUnchanged') if key in item}
        for item in report['files']], 'failureCode': report.get('failureCode'),
        'resultSha256': sha((output / 'result.json').read_bytes()), 'result': str(output / 'result.json')}))
    return 0 if report['completed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('taobao', 'pinduoduo', 'compatibility-index', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--compatibility-index-sha256', required=True)
    parser.add_argument('--source-head', required=True)
    try:
        return run(parser.parse_args())
    except Exception as exc:
        print(json.dumps({'completed': False, 'phase': 'preflight',
                          'failureCode': str(exc) if isinstance(exc, CheckFailed) else 'private_detail_withheld'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
