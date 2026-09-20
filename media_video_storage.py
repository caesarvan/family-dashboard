"""One additive encrypted-video cache table; authorization stays in MediaLibrary.

No decoder, source URL, network or production migration entry point. The
initializer adds an empty table plus a tombstone cleanup trigger in one SQLite
transaction without modifying any existing photo, import or receipt row.
"""
import sqlite3

from media_crypto import MAX_VIDEO_CIPHER_BYTES

SCHEMA_SQL = f'''
CREATE TABLE IF NOT EXISTS media_video_cache(
 media_id TEXT PRIMARY KEY REFERENCES media_items(id) ON DELETE CASCADE,
 cache_key TEXT NOT NULL UNIQUE,
 cipher BLOB NOT NULL CHECK(length(cipher)>0 AND length(cipher)<={MAX_VIDEO_CIPHER_BYTES}),
 created_at REAL NOT NULL
);
CREATE TRIGGER IF NOT EXISTS media_video_deleted
AFTER UPDATE OF state ON media_items
WHEN NEW.state='deleted'
BEGIN
 DELETE FROM media_video_cache WHERE media_id=NEW.id;
END;
'''


def initialize_media_video_storage(con):
    """Require established media parents and an unclaimed FK-enabled connection."""
    if con.in_transaction or con.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
        raise RuntimeError('Video storage initialization needs a clean foreign-key connection')
    parents = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'media_items', 'media_imports', 'media_tv_grants'} <= parents:
        raise RuntimeError('Video storage requires existing media parents')
    try:
        con.execute('BEGIN IMMEDIATE')
        statement=''
        expected=[]
        for line in SCHEMA_SQL.splitlines(keepends=True):
            statement+=line
            if sqlite3.complete_statement(statement):
                expected.append(statement.strip().rstrip(';'))
                con.execute(statement)
                statement=''
        if statement.strip() or len(expected)!=2:
            raise RuntimeError('Video schema statement boundary changed')
        for (kind,name),sql in zip((('table','media_video_cache'),('trigger','media_video_deleted')),expected):
            current=con.execute('SELECT sql FROM sqlite_master WHERE type=? AND name=?',(kind,name)).fetchone()
            normalize=lambda value:' '.join(value.replace(' IF NOT EXISTS','').split())
            if not current or normalize(current[0])!=normalize(sql):
                raise RuntimeError('Existing video storage schema differs from reviewed DDL')
        con.commit()
    except BaseException:
        con.rollback()
        raise
