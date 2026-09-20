"""Explicit per-TV journey scope and owner-only durable start receipts."""

SCHEMA_SQL = '''
CREATE TABLE media_playback_journeys(
 device_id TEXT PRIMARY KEY NOT NULL REFERENCES media_playback(device_id) ON DELETE CASCADE,
 journey_id TEXT REFERENCES journey_workflows(id) ON DELETE SET NULL,
 route_id TEXT REFERENCES journey_routes(id) ON DELETE SET NULL,
 route_selected INTEGER NOT NULL CHECK(typeof(route_selected)='integer' AND route_selected IN (0,1)),
 started_by TEXT REFERENCES users(id) ON DELETE SET NULL,
 start_request_id TEXT NOT NULL CHECK(length(start_request_id)=32 AND start_request_id NOT GLOB '*[^0-9a-f]*'),
 created_at REAL NOT NULL CHECK(created_at>=0),
 updated_at REAL NOT NULL CHECK(updated_at>=0),
 CHECK(route_selected=1 OR route_id IS NULL));
CREATE TABLE media_playback_operations(
 owner TEXT NOT NULL REFERENCES users(id),
 request_id TEXT NOT NULL CHECK(length(request_id)=32 AND request_id NOT GLOB '*[^0-9a-f]*'),
 payload_digest TEXT NOT NULL CHECK(length(payload_digest)=64 AND payload_digest NOT GLOB '*[^0-9a-f]*'),
 device_id TEXT NOT NULL CHECK(length(device_id)=24 AND device_id NOT GLOB '*[^0-9a-f]*'),
 kind TEXT NOT NULL CHECK(kind='journey_start'),
 result_revision INTEGER NOT NULL CHECK(typeof(result_revision)='integer' AND result_revision BETWEEN 1 AND 9007199254740991),
 completed_at REAL NOT NULL CHECK(completed_at>=0),
 PRIMARY KEY(owner,request_id));
'''


def init_schema(con):
    """Caller owns an explicit foreign-key transaction, including atomic DDL."""
    if not con.in_transaction or con.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
        raise RuntimeError('Trip playback initialization requires an active foreign-key transaction')
    parents = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'users', 'media_playback', 'journey_workflows', 'journey_routes'} <= parents:
        raise RuntimeError('Trip playback initialization requires its parent tables')
    for statement in SCHEMA_SQL.split(';'):
        statement = statement.strip()
        if not statement:
            continue
        name = statement.split('(', 1)[0].split()[-1]
        row = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
        if row:
            if row[0].strip().rstrip(';') != statement:
                raise RuntimeError('Trip playback schema mismatch: '+name)
        else:
            con.execute(statement)
