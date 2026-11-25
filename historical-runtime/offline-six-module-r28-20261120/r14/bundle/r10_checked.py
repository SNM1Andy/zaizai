import os
import sqlite3
from contextlib import closing
from pathlib import Path
from evidence_io import plain, read, require, same, sha
COMP = Path(__file__).resolve().parent/'components'
def open_ro(path):
    # Only quiescent images may enter immutable mode. Never discard a hot journal.
    plain(path)
    for suffix in ('-wal', '-shm', '-journal'):
        require(not os.path.lexists(str(path) + suffix), 'SQLite sidecar present')
    db = sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True, timeout=0)
    db.execute('PRAGMA query_only=ON')
    db.execute('PRAGMA temp_store=MEMORY')
    return db

def inventory(root):
    plain(root, directory=True)
    files, dirs = {}, []
    for path in sorted(root.rglob('*')):
        rel = path.relative_to(root).as_posix()
        if path.is_dir():
            plain(path, directory=True)
            dirs.append(rel)
        else:
            files[rel] = sha(read(root, rel))
    return dict(files=files, directories=dirs)

def sql_schema(db):
    return db.execute('SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY name').fetchall()

def check_db(path, schema):
    with closing(open_ro(path)) as db, closing(sqlite3.connect(':memory:')) as ref:
        ref.executescript((COMP/(schema+'.sql')).read_text(encoding='utf8'))
        same(sql_schema(db),sql_schema(ref),schema+' project DDL')
        same(db.execute('PRAGMA integrity_check').fetchall(), [('ok',)],schema+' integrity')
        same(db.execute('PRAGMA foreign_key_check').fetchall(), [], schema+' foreign keys')
        tables = ('authority','intent') if schema=='slot' else ('authority','action','binding')
        return {t:db.execute('SELECT * FROM '+t+' ORDER BY 1').fetchall() for t in tables}

def fresh_file(path, data):
    with path.open('xb') as stream:
        require(stream.write(data)==len(data),'short write')
        stream.flush()
        os.fsync(stream.fileno())

def image(source, dest):
    # Destination exists exclusively for this call. No fallback to a byte-copy.
    dest.touch(exist_ok=False)
    progress = []
    with closing(open_ro(source)) as src, closing(sqlite3.connect(
            dest.as_uri()+'?mode=rw',uri=True,timeout=0)) as out:
        out.execute('PRAGMA synchronous=FULL')
        src.backup(out,pages=16,progress=lambda status,left,total: progress.append([status,left,total]))
    require(progress and progress[-1][0]==sqlite3.SQLITE_DONE and progress[-1][1]==0,'incomplete backup')
    return progress
