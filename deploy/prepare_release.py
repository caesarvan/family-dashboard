"""Build a stable allowlisted source archive, never initialize credentials.

Concurrent agent changes invalidate the candidate before replacing the previous
release. The manifest records exactly which source bytes are in the archive.
"""
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tarfile


ROOT = Path(__file__).resolve().parents[1]
FILES = ['app.py','member_sessions.py','tv_display.py','sync_health.py','cloud_accounts.py','cloud_providers.py','sync_worker.py','shopping_media.py','shopping_settlement.py','household_routines.py','spending_observations.py',
         'finance_baseline.py','finance_source_bridge.py','journey_time.py','household_spaces.py','journey_workflows.py','journey_documents.py','finance_hub.py',
         'home_assistant.py','calendar_publish.py','task_publish.py','financial_files.py','investment_import.py','dashboard_preferences.py','data_portability.py','requirements.txt',
         'Dockerfile','compose.yaml','pytest.ini','.dockerignore','.gitignore','README.md']
FOLDERS = ['static','deploy','docs','tests']


def prepare(root=ROOT, access=None):
    root = Path(root).resolve(strict=True)
    access = Path(access or Path.home() / 'Documents' / 'Codex' / 'family-dashboard-access')
    access.mkdir(parents=True, exist_ok=True)
    paths = [root / name for name in FILES]
    for folder in FOLDERS:
        if not (root / folder).is_dir():
            raise RuntimeError('Required source directory missing: ' + folder)
        paths.extend(p for p in (root / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
    paths = sorted(set(paths))
    blobs = {}
    for path in paths:
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
            raise RuntimeError('Source symlink outside release boundary')
        name = path.relative_to(root).as_posix()
        if any(part.startswith('.env') for part in path.relative_to(root).parts) or '.sqlite' in name or 'credentials' in name.lower():
            raise RuntimeError('Private runtime file found in source allowlist')
        blobs[name] = path.read_bytes()
    manifest = {'createdAt': datetime.now(timezone.utc).isoformat(),
                'files': {name: hashlib.sha256(value).hexdigest() for name, value in blobs.items()},
                'excluded': ['credentials', 'runtime databases', 'private finance imports', 'test-results']}
    destination = access / 'release.tar.gz'
    candidate = access / 'release.candidate.tar.gz'
    with tarfile.open(candidate, 'w:gz') as archive:
        for name, value in blobs.items():
            info = tarfile.TarInfo(name)
            info.size = len(value)
            info.mode = 0o755 if name.startswith('deploy/') and name.endswith('.sh') else 0o644
            info.mtime = int((root / name).stat().st_mtime)
            archive.addfile(info, BytesIO(value))
        value = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
        info = tarfile.TarInfo('RELEASE-MANIFEST.json')
        info.size, info.mode = len(value), 0o644
        archive.addfile(info, BytesIO(value))
    if any(hashlib.sha256((root / name).read_bytes()).hexdigest() != digest for name, digest in manifest['files'].items()):
        raise RuntimeError('Sources changed while packaging; previous release retained. Retry after agents finish.')
    with tarfile.open(candidate) as archive:
        for name, digest in manifest['files'].items():
            if hashlib.sha256(archive.extractfile(name).read()).hexdigest() != digest:
                raise RuntimeError('Archive checksum verification failed')
    candidate.replace(destination)
    with destination.open('rb') as stream:
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'archive': str(destination), 'files': len(blobs), 'sha256': checksum,
            'manifest': 'RELEASE-MANIFEST.json', 'credentialsTouched': False}


if __name__ == '__main__':
    print(json.dumps(prepare(), ensure_ascii=False))
