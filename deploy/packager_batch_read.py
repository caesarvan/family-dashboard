"""Opt-in transformation of the reviewed account packager, never an entrypoint.

The next release adapter may call transform_prepare() after checking its parent
script hash. This module only returns bytes; it never packages, binds or reads
Git. Existing generated tools remain unchanged.
"""
from __future__ import annotations

import ast

READER_SHA256 = 'c71a4e60e65b45581899d0e2347f2e510bdc37fd508559155db1df8d3c3cd89b'

OLD_GIT = """def git(*args):
    return subprocess.check_output(['git', '-C', str(REPO), *args], stderr=subprocess.PIPE)
"""
NEW_GIT = """def git(*args):
    return subprocess.check_output(
        ['git', '--no-replace-objects', '--no-optional-locks', '-C', str(REPO), *args],
        stderr=subprocess.PIPE,
        env=dict(os.environ, GIT_NO_LAZY_FETCH='1', GIT_TERMINAL_PROMPT='0'), timeout=60)
"""
OLD_ANCESTRY = """    subprocess.run(['git', '-C', str(REPO), 'merge-base', '--is-ancestor', config['integration'], config['main']],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
"""
NEW_ANCESTRY = """    git('merge-base', '--is-ancestor', config['integration'], config['main'])
"""
LOADER = '''def load_blob_reader(head):
    # Bootstrap from the same immutable commit, not an import of a working file.
    raw = git('show', head + ':deploy/git_blobs.py')
    need(len(raw) <= MAX_FILE and digest(raw) == %r,
         'Reviewed batch Git reader changed')
    namespace = {'__name__': 'reviewed_packager_blob_reader',
                 '__file__': str(REPO / 'deploy/git_blobs.py')}
    exec(compile(raw, namespace['__file__'], 'exec'), namespace)
    return namespace['read_git_blobs']


''' % READER_SHA256

OLD_BOOTSTRAP = """    tracked = tracked_files(head)
    docker = git('show', head + ':Dockerfile')
"""
NEW_BOOTSTRAP = """    tracked = tracked_files(head)
    read_blobs = load_blob_reader(head)
    bootstrap = read_blobs(REPO, head, ('Dockerfile', 'deploy/prepare_release.py'))
    docker = bootstrap['Dockerfile']
    selected = selected_sources(tracked, bootstrap['deploy/prepare_release.py'])
"""
OLD_RECORDS = """    for record in (evidence, tested):
        need(git('rev-parse', record['sourceHead'] + '^{tree}').decode().strip() == record['sourceTree'],
             'Build source commit/tree mismatch')
        build_names = tracked_files(record['sourceHead'])
        need(set(record['inputFiles']) == contract['required_inputs'](tracked, docker)
             == contract['required_inputs'](build_names, git('show', record['sourceHead'] + ':Dockerfile')),
             'Build input set is incomplete')
        for name, sha in record['inputFiles'].items():
            need(digest(git('show', head + ':' + name)) == sha
                 == digest(git('show', record['sourceHead'] + ':' + name)), 'Runtime source changed after tested build')
"""
NEW_RECORDS = """    input_names = contract['required_inputs'](tracked, docker)
    need(all(set(record['inputFiles']) == input_names for record in (evidence, tested)),
         'Build input set is incomplete')
    # Per-inspection only: package readback and binder each start fresh here.
    main_blobs = read_blobs(REPO, head, sorted(selected | input_names))
    commit_blobs = {head: main_blobs}
    for record in (evidence, tested):
        need(git('rev-parse', record['sourceHead'] + '^{tree}').decode().strip() == record['sourceTree'],
             'Build source commit/tree mismatch')
        build_names = tracked_files(record['sourceHead'])
        if record['sourceHead'] not in commit_blobs:
            commit_blobs[record['sourceHead']] = read_blobs(
                REPO, record['sourceHead'], sorted(input_names | {'Dockerfile'}))
        build_blobs = commit_blobs[record['sourceHead']]
        need(input_names == contract['required_inputs'](build_names, build_blobs['Dockerfile']),
             'Build input set is incomplete')
        for name, sha in record['inputFiles'].items():
            need(digest(main_blobs[name]) == sha == digest(build_blobs[name]),
                 'Runtime source changed after tested build')
"""
OLD_SELECTED = """    selected = selected_sources(tracked, git('show', head + ':deploy/prepare_release.py'))
    blobs = {}
    for name in sorted(selected):
        raw = git('show', head + ':' + name)
        need(len(raw) <= MAX_FILE and read_bytes(REPO / name) == raw, 'Working source differs from frozen tracked bytes')
        blobs[name] = raw
"""
NEW_SELECTED = """    blobs = {}
    for name in sorted(selected):
        raw = main_blobs[name]
        need(len(raw) <= MAX_FILE and read_bytes(REPO / name) == raw, 'Working source differs from frozen tracked bytes')
        blobs[name] = raw
"""


def _replace_once(code: str, old: str, new: str) -> str:
    if code.count(old) != 1:
        raise ValueError('Expected exactly one reviewed packager fragment')
    return code.replace(old, new, 1)


def transform_prepare(source: bytes) -> bytes:
    """Transform an already hash-reviewed account prepare-package.py once.

    No fallback to per-file reads, mutable refs, working imports, or cross-call
    caches. All functions except git/git_identity/inspect_inputs remain exact
    AST equivalents; callers still review the complete generated byte delta.
    """
    if not isinstance(source, bytes) or len(source) > 100_000:
        raise ValueError('Bounded UTF-8 source bytes required')
    code = source.decode('utf-8').replace('\r\n', '\n')
    before = ast.parse(code)
    functions = {node.name: node for node in before.body if isinstance(node, ast.FunctionDef)}
    if len(functions) != sum(isinstance(node, ast.FunctionDef) for node in before.body):
        raise ValueError('Duplicate packager function')
    if 'load_blob_reader' in functions or 'FINANCE_ACCOUNTS_SCHEMA_SQL' not in code:
        raise ValueError('Expected an unmodified account packager')
    for name in ('git', 'git_identity', 'tracked_files', 'selected_sources', 'inspect_inputs', 'prepare'):
        if name not in functions:
            raise ValueError('Required packager guard absent')
    if any(isinstance(n, ast.Import) and any(a.name == 'os' for a in n.names) for n in before.body):
        raise ValueError('Unexpected existing os import')
    code = _replace_once(code, 'import json\n', 'import json\nimport os\n')
    for old, new in ((OLD_GIT, NEW_GIT), (OLD_ANCESTRY, NEW_ANCESTRY),
                     (OLD_BOOTSTRAP, NEW_BOOTSTRAP), (OLD_RECORDS, NEW_RECORDS),
                     (OLD_SELECTED, NEW_SELECTED)):
        code = _replace_once(code, old, new)
    code = _replace_once(code, 'def inspect_inputs(config, contract):', LOADER + 'def inspect_inputs(config, contract):')
    after = ast.parse(code)
    revised = {node.name: node for node in after.body if isinstance(node, ast.FunctionDef)}
    if set(revised) != set(functions) | {'load_blob_reader'}:
        raise ValueError('Unexpected generated function set')
    for name, node in functions.items():
        if name not in {'git', 'git_identity', 'inspect_inputs'} and ast.dump(node) != ast.dump(revised[name]):
            raise ValueError('Unrelated packager guard changed: ' + name)
    return code.encode('utf-8')
