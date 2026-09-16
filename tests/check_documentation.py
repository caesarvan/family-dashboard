"""Read-only documentation syntax validation and isolated restore simulations.

Only test-results/ artifacts and TemporaryDirectory fixtures are written.
Deployment shell and PowerShell examples are parsed, never executed.
"""
from __future__ import annotations
import ast
from contextlib import closing
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'test-results' / 'documentation-validation.json'
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
REPORT = {'checkedAt': datetime.now(timezone.utc).isoformat(), 'scope': 'README.md and docs/**/*.md; local syntax only; no deployment or network calls', 'documents': [], 'checks': [], 'failures': [], 'restore': []}

def record(kind, source, line, ok, detail=''):
    item = {'kind': kind, 'source': source, 'line': line, 'ok': ok}
    if detail:
        item['detail'] = detail
    REPORT['checks'].append(item)
    if not ok:
        REPORT['failures'].append(item)


def blocks(path):
    content = path.read_text(encoding='utf-8-sig')
    opened = None
    plain = []
    result = []
    for no, line in enumerate(content.splitlines(), 1):
        m = re.match(r'^\s{0,3}(`{3,}|~{3,})(.*)$', line)
        if opened:
            fence, lang, first, body = opened
            if m and set(m[1]) == {fence[0]} and len(m[1]) >= len(fence) and not m[2].strip():
                result.append((lang, first, '\n'.join(body) + '\n'))
                opened = None
            else:
                body.append(line)
        elif m:
            opened = (m[1], m[2].strip().split(' ', 1)[0].lower(), no, [])
        else:
            plain.append((no, line))
    record('fence_balance', path.relative_to(ROOT).as_posix(), 1, opened is None, 'Unclosed fence' if opened else '')
    return result, plain


class ExplicitAnchors(HTMLParser):
    def __init__(self):
        super().__init__()
        self.anchors = set()

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if value and (key == 'id' or (tag == 'a' and key == 'name')):
                self.anchors.add(value)


def heading_anchors(path):
    _, plain = blocks_cache[path]
    seen = {}
    explicit = ExplicitAnchors()
    explicit.feed('\n'.join(line for _, line in plain))
    anchors = explicit.anchors
    for _, line in plain:
        if re.match(r'^#{1,6}\s+', line):
            h = re.sub(r'^#{1,6}\s+|\s+#+\s*$', '', line).lower()
            h = re.sub(r'\[([^]]+)\]\([^)]+\)', r'\1', h)
            h = re.sub(r'<[^>]+>', '', h)
            h = re.sub(r'[^\w\-\s]', '', h, flags=re.UNICODE).replace(' ', '-')
            n = seen.get(h, 0)
            seen[h] = n + 1
            anchors.add(h if not n else f'{h}-{n}')
    return anchors


def parse_powershell(code):
    parser = r"""
$parseTokens = $null
$parseErrors = $null
$snippet = [Console]::In.ReadToEnd()
[void][System.Management.Automation.Language.Parser]::ParseInput($snippet, [ref]$parseTokens, [ref]$parseErrors)
$result = @($parseErrors | ForEach-Object { @{ message=$_.Message; line=$_.Extent.StartLineNumber; text=$_.Extent.Text } })
ConvertTo-Json -InputObject $result -Compress -Depth 5
if ($parseErrors.Count -gt 0) { exit 1 }
"""
    executable = shutil.which('pwsh') or shutil.which('powershell')
    if not executable:
        return False, 'No PowerShell parser available'
    p = subprocess.run([executable, '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', parser], input=code, text=True, encoding='utf-8', capture_output=True, timeout=30)
    return p.returncode == 0, p.stdout.strip() or p.stderr.strip()


def db(path, marker, registry=False, ids=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as con:
        if registry:
            con.executescript('CREATE TABLE households(id TEXT PRIMARY KEY, slug TEXT, name TEXT, created_at TEXT); CREATE TABLE household_invitations(hash TEXT PRIMARY KEY);')
            con.executemany('INSERT INTO households VALUES(?,?,?,?)', [(x, 'home' if x == 'default' else 'test-home', marker, '2026-09-15') for x in ids])
        else:
            con.executescript('CREATE TABLE users(id TEXT PRIMARY KEY); CREATE TABLE entities(id TEXT PRIMARY KEY, data TEXT); CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT);')
            con.executemany('INSERT INTO users VALUES(?)', [('member1',), ('member2',)])
            con.execute('INSERT INTO entities VALUES(?,?)', ('marker', marker))
        con.commit()


def marker(path, registry=False):
    with closing(sqlite3.connect(path)) as con:
        return con.execute("SELECT name FROM households WHERE id='default'" if registry else "SELECT data FROM entities WHERE id='marker'").fetchone()[0]


def set_marker(path, value, registry=False):
    with closing(sqlite3.connect(path)) as con:
        con.execute('UPDATE households SET name=?' if registry else "UPDATE entities SET data=? WHERE id='marker'", (value,))
        con.commit()


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def restore_tests():
    path = ROOT / 'docs' / 'DEPLOYMENT.md'
    candidates = [code for lang, line, code in blocks_cache[path][0] if 'restore_mode=' in code and 'from contextlib import ExitStack' in code]
    assert len(candidates) == 1, 'Expected exactly one documented restore command'
    shell = candidates[0]
    raw = re.search(r"<<'PY'\n(.*?)\nPY(?:\n|$)", shell, re.S).group(1)
    ast.parse(raw)
    assert raw.count("root = Path('/data').resolve(strict=True)") == 1
    imports = {n.module for n in ast.walk(ast.parse(raw)) if isinstance(n, ast.ImportFrom)} | {v.name for n in ast.walk(ast.parse(raw)) if isinstance(n, ast.Import) for v in n.names}
    assert imports <= {'contextlib', 'pathlib', 'hashlib', 'json', 're', 'sqlite3', 'sys'}, imports
    adapted = raw.replace("root = Path('/data').resolve(strict=True)", "root = Path(sys.argv.pop(1)).resolve(strict=True)")
    REPORT['restoreExampleSha256'] = hashlib.sha256(raw.encode()).hexdigest()
    REPORT['restoreAdaptation'] = 'Only root = Path(\'/data\') changed to a temporary-directory argument; documented restore logic otherwise unchanged.'
    spec = importlib.util.spec_from_file_location('docs_backup_under_test', ROOT / 'deploy' / 'backup.py')
    backup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backup)
    uid = 'a' * 24
    scenarios = [('platform_valid', 'platform', 'default'), ('single_default', 'household', 'default'), ('single_child', 'household', uid), ('bad_hash_no_overwrite', 'platform', 'default'), ('bad_mapping_no_overwrite', 'platform', 'default'), ('bad_member_no_overwrite', 'platform', 'default'), ('missing_current_registration_no_overwrite', 'household', uid)]
    for name, mode, chosen in scenarios:
        with tempfile.TemporaryDirectory(prefix='family-doc-restore-') as folder:
            root = Path(folder)
            targets = {'default': root / 'household.sqlite3', uid: root / 'spaces' / uid / 'household.sqlite3', 'registry': root / 'platform.sqlite3'}
            db(targets['default'], 'old-default')
            db(targets[uid], 'old-child')
            db(targets['registry'], 'old-registry', True, ['default', uid])
            result = backup.backup_all(root)
            manifest_path = root / 'backups' / result['manifest']
            manifest = json.loads(manifest_path.read_text())
            for key, target in targets.items():
                set_marker(target, 'new-' + key, key == 'registry')
            if name == 'bad_hash_no_overwrite':
                # Corrupt the last snapshot, after other sources have passed validation.
                manifest['snapshots'][-1]['sha256'] = '0' * 64
            if name == 'bad_mapping_no_overwrite':
                entry = next(x for x in manifest['snapshots'] if '/platform-' in '/' + x['path'])
                source = root / entry['path']
                with closing(sqlite3.connect(source)) as con:
                    con.execute('UPDATE households SET id=? WHERE id=?', ('b' * 24, uid))
                    con.commit()
                entry.update(bytes=source.stat().st_size, sha256=checksum(source))
            if name == 'bad_member_no_overwrite':
                entry = manifest['snapshots'][-1]
                source = root / entry['path']
                with closing(sqlite3.connect(source)) as con:
                    con.execute("DELETE FROM users WHERE id='member2'")
                    con.commit()
                entry.update(bytes=source.stat().st_size, sha256=checksum(source))
            if name == 'missing_current_registration_no_overwrite':
                with closing(sqlite3.connect(targets['registry'])) as con:
                    con.execute('DELETE FROM households WHERE id=?', (uid,))
                    con.commit()
            manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
            before = {key: checksum(target) for key, target in targets.items()}
            run = subprocess.run([sys.executable, '-X', 'utf8', '-c', adapted, str(root), result['manifest'], mode, chosen], capture_output=True, text=True, encoding='utf-8', timeout=30)
            after = {key: checksum(target) for key, target in targets.items()}
            expected_failure = name.endswith('no_overwrite')
            if expected_failure:
                ok = run.returncode != 0 and before == after
            else:
                selected = set(targets) if mode == 'platform' else {chosen}
                ok = run.returncode == 0
                for key, target in targets.items():
                    expected = ('old-registry' if key == 'registry' else 'old-default' if key == 'default' else 'old-child') if key in selected else 'new-' + key
                    ok &= marker(target, key == 'registry') == expected
                    if key not in selected:
                        ok &= before[key] == after[key]
            item = {'scenario': name, 'ok': bool(ok), 'exitCode': run.returncode, 'unchangedTargets': [key for key in targets if before[key] == after[key]], 'message': (run.stdout or run.stderr).strip()}
            REPORT['restore'].append(item)
            if not ok:
                REPORT['failures'].append({'kind': 'restore', **item})


documents = [ROOT / 'README.md'] + sorted((ROOT / 'docs').rglob('*.md'))
blocks_cache = {path: blocks(path) for path in documents}
for path in documents:
    source = path.relative_to(ROOT).as_posix()
    REPORT['documents'].append({'path': source, 'sha256': checksum(path)})
    snippets, plain = blocks_cache[path]
    for line, text in plain:
        for match in re.finditer(r'!?\[[^\]]+\]\((<[^>]+>|[^)]+)\)', text):
            link = match.group(1).strip().strip('<>')
            link = re.sub(r'\s+"[^"]*"$', '', link)
            parts = urlsplit(link)
            if parts.scheme or parts.netloc:
                continue
            target = (path.parent / unquote(parts.path)).resolve() if parts.path else path
            record('relative_link', source, line, target.exists(), link)
            if parts.fragment and target in blocks_cache:
                fragment = unquote(parts.fragment)
                record('heading_anchor', source, line, fragment in heading_anchors(target), link)
    for lang, line, code in snippets:
        if lang == 'json':
            try:
                json.loads(code)
                record('json', source, line, True)
            except json.JSONDecodeError as exc:
                record('json', source, line, False, str(exc))
        elif lang in {'powershell', 'pwsh', 'ps1'}:
            ok, detail = parse_powershell(code)
            record('powershell_parse_only', source, line, ok, detail if not ok else '')
        elif lang in {'sh', 'shell', 'bash'}:
            shell = shutil.which('sh')
            if not shell:
                record('sh_n_parse_only', source, line, False, 'No sh executable')
            else:
                run = subprocess.run([shell, '-n'], input=code, capture_output=True, text=True, encoding='utf-8', timeout=30)
                record('sh_n_parse_only', source, line, run.returncode == 0, run.stderr.strip())
            for embedded in re.finditer(r"<<'PY'\n(.*?)\nPY(?:\n|$)", code, re.S):
                try:
                    ast.parse(embedded.group(1))
                    record('python_heredoc_parse_only', source, line, True)
                except SyntaxError as exc:
                    record('python_heredoc_parse_only', source, line, False, str(exc))
        elif lang in {'python', 'py'}:
            try:
                ast.parse(code)
                record('python_parse_only', source, line, True)
            except SyntaxError as exc:
                record('python_parse_only', source, line, False, str(exc))
try:
    restore_tests()
except Exception as exc:
    REPORT['failures'].append({'kind': 'restore_harness', 'detail': repr(exc)})
REPORT['counts'] = {kind: sum(x['kind'] == kind for x in REPORT['checks']) for kind in sorted({x['kind'] for x in REPORT['checks']})}
REPORT['success'] = not REPORT['failures']
OUTPUT.write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'success': REPORT['success'], 'documents': len(documents), 'counts': REPORT['counts'], 'restore': REPORT['restore'], 'failures': REPORT['failures'], 'report': str(OUTPUT)}, ensure_ascii=False, indent=2))
sys.exit(0 if REPORT['success'] else 1)
