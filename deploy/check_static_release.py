"""Read-only 43-to-43 checks. Never initializes, restores, or ticks an app.

The caller must stop every writer before snapshot/backup and keep ingress and
sync closed through the final comparison. Inputs and this dependency are pinned
by the release controller. Snapshot rows contain hashes, never actual values.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1]
DEPENDENCY = 'deploy/check_journey_documents_migration.py'
DEPENDENCY_SHA256 = '11adc9f40bf68aaca7015f3c9f18f92c7aa648b6c379b0812b60b5d22cd2781f'


def load_dependency():
    path = SOURCE_ROOT / DEPENDENCY
    if hashlib.sha256(path.read_bytes()).hexdigest() != DEPENDENCY_SHA256:
        raise RuntimeError('static_verifier_dependency_changed')
    spec = importlib.util.spec_from_file_location('static_fingerprint_dependency', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = load_dependency()


def snapshot(root):
    value = M.snapshot(root, allow_new=True)
    schema, tables = M.expected_addition(M.schema_definition()['sql'])
    for household in value['households'].values():
        # Existing document rows and BLOBs are allowed. Its frozen DDL, indexes,
        # trigger, columns and foreign keys must still be the approved schema.
        if household['newSchemaSha256'] != schema:
            raise RuntimeError('document_schema_changed')
        for name, expected in tables.items():
            actual = household['tables'][name]
            if any(actual[k] != expected[k] for k in ('columns', 'foreignKeys')):
                raise RuntimeError('document_columns_changed')
    return value


def run(action, root, inputs):
    if action not in ('snapshot', 'validate-backup', 'check'):
        raise RuntimeError('unknown_static_check')
    root, inputs = Path(root).resolve(strict=True), Path(inputs).resolve(strict=True)

    def read(name):
        return json.loads(M.checked_path(inputs, name).read_bytes())

    current = snapshot(root)
    if action == 'snapshot':
        return current
    before = read('before.json')
    if current != before:
        raise RuntimeError('stopped_database_contents_changed')
    proof = M.validated_backup(root, before, read('backup.json'))
    if action == 'validate-backup':
        return proof
    if read('backup-verification.json') != proof:
        raise RuntimeError('backup_proof_changed')
    return {'households': len(before['households']), 'originalTablesPreserved': 43,
            'newTables': 0, 'schemaIndexesAndTriggersVerified': True,
            'allOriginalRowsAndSequencesPreserved': True, 'backup': proof}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('snapshot', 'validate-backup', 'check'))
    parser.add_argument('--data-dir', default=os.environ.get('DATA_DIR'))
    parser.add_argument('--inputs-dir', default='/release-check')
    args = parser.parse_args(argv)
    if not args.data_dir:
        parser.error('--data-dir or DATA_DIR is required')
    try:
        result = run(args.action, args.data_dir, args.inputs_dir)
    except Exception:
        raise SystemExit('static_database_verification_failed') from None
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
