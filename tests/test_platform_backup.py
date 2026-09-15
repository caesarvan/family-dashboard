import importlib.util
import json
from pathlib import Path
import sqlite3
import pytest
from test_app import app, member
from test_household_spaces import create_space


def backup_module():
    spec=importlib.util.spec_from_file_location('platform_backup',Path(__file__).resolve().parents[1]/'deploy'/'backup.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backups_cover_registry_and_both_households(app):
    create_space(app)
    root=Path(app.config['DATA_DIR'])
    result=backup_module().backup_all(root)
    assert result['databases']==3
    manifest=json.loads((root/'backups'/result['manifest']).read_text())
    for item in manifest['snapshots']:
        target=root/item['path']
        assert target.is_file() and target.stat().st_size==item['bytes']
        with sqlite3.connect(target.as_uri()+'?mode=ro',uri=True) as con:
            assert con.execute('PRAGMA quick_check').fetchone()[0]=='ok'
    registry=next(root/x['path'] for x in manifest['snapshots'] if Path(x['path']).name.startswith('platform-'))
    with sqlite3.connect(registry) as con:
        assert con.execute('SELECT count(*) FROM households').fetchone()[0]==2


def test_backup_missing_source_is_not_created(tmp_path):
    with pytest.raises(FileNotFoundError):
        backup_module().backup_all(tmp_path)
    assert not (tmp_path/'household.sqlite3').exists()


def test_retention_never_breaks_complete_manifests_after_incomplete_runs(app):
    import shutil
    root=Path(app.config['DATA_DIR'])
    module=backup_module()
    module.backup_all(root)
    # These stand for an interrupted run that captured one database only.
    sample=next((root/'backups').glob('household-*.sqlite3'))
    for i in range(18):
        shutil.copyfile(sample,root/'backups'/f'household-99990101T0000{i:02d}Z.sqlite3')
    for _ in range(15):
        module.backup_all(root)
    manifests=list((root/'backups').glob('manifest-*.json'))
    assert len(manifests)==14
    for manifest in manifests:
        for item in json.loads(manifest.read_text())['snapshots']:
            assert (root/item['path']).exists()
    assert len(list((root/'backups').glob('household-*.sqlite3')))==14
