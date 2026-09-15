"""SQLite online backups for the registry and each registered household.

Registry is captured first so every referenced household is included. Separate
databases are not a global transaction; each individual SQLite snapshot is.
"""
from datetime import datetime, timezone
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3


def backup_all(root):
    root = Path(root).resolve(strict=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    results = []
    folders = set()

    def capture(source, prefix):
        source = source.resolve(strict=True)
        if not source.is_relative_to(root) or not source.is_file() or source.stat().st_size == 0:
            raise RuntimeError('Invalid backup source')
        folder = source.parent / 'backups'
        folder.mkdir(mode=0o700, exist_ok=True)
        folders.add(folder)
        destination = folder / (prefix + '-' + stamp + '.sqlite3')
        partial = destination.with_suffix('.partial')
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src, closing(sqlite3.connect(partial)) as target:
            src.backup(target)
            if target.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise RuntimeError('Backup integrity check failed')
        partial.chmod(0o600)
        partial.replace(destination)
        with destination.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        results.append({'path': destination.relative_to(root).as_posix(), 'bytes': destination.stat().st_size,
                        'sha256': digest})
        return destination

    registry = root / 'platform.sqlite3'
    households = []
    if registry.exists():
        snapshot = capture(registry, 'platform')
        with closing(sqlite3.connect(snapshot.as_uri() + '?mode=ro', uri=True)) as con:
            households = [r[0] for r in con.execute("SELECT id FROM households WHERE id!='default'")]
    capture(root / 'household.sqlite3', 'household')
    for uid in households:
        if not re.fullmatch(r'[a-f0-9]{24}', uid):
            raise RuntimeError('Invalid household registry entry')
        capture(root / 'spaces' / uid / 'household.sqlite3', 'household')
    manifest = root / 'backups' / ('manifest-' + stamp + '.json')
    manifest.write_text(json.dumps({'createdAt': stamp, 'snapshots': results}, indent=2), encoding='utf-8')
    manifest.chmod(0o600)
    manifests = sorted((root / 'backups').glob('manifest-*.json'))
    kept_manifests = manifests[-14:]
    protected = set()
    for kept in kept_manifests:
        for item in json.loads(kept.read_text(encoding='utf-8'))['snapshots']:
            referenced = (root / item['path']).resolve(strict=True)
            if not referenced.is_relative_to(root) or referenced.parent.name != 'backups':
                raise RuntimeError('Invalid backup manifest reference')
            protected.add(referenced)
    for folder in folders:
        for pattern in ('household-*.sqlite3', 'platform-*.sqlite3'):
            snapshots = sorted(folder.glob(pattern))
            # Preserve legacy standalone history during the first 14 manifest runs.
            legacy_keep = set(snapshots[-14:]) if len(kept_manifests) < 14 else set()
            for old in snapshots:
                if old.resolve() not in protected and old not in legacy_keep and old.is_file() and not old.is_symlink():
                    old.unlink()
    for old in manifests[:-14]:
        if old.is_file() and not old.is_symlink():
            old.unlink()
    return {'manifest': manifest.name, 'databases': len(results)}


if __name__ == '__main__':
    print(json.dumps(backup_all(os.environ.get('DATA_DIR', '/data'))))
