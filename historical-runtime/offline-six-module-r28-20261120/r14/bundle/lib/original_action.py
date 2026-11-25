"""Synthetic dispatch authority shared by cold recovery and ordinary admission."""
from contextlib import closing, contextmanager
from pathlib import Path
import secrets
import sqlite3


def enroll(path, namespace, actions, jobs):
    """Only the independent synthetic planner calls this, before any dispatch."""
    with path.open("xb"):
        pass
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript("""
            PRAGMA synchronous=FULL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE authority(namespace TEXT PRIMARY KEY);
            CREATE TABLE action(original_id TEXT PRIMARY KEY, request_sha256 TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('PLANNED','RESERVED','UNKNOWN','COMPLETED')),
                claim TEXT);
            CREATE TABLE binding(job TEXT NOT NULL, campaign TEXT NOT NULL,
                original_id TEXT NOT NULL REFERENCES action(original_id), PRIMARY KEY(job,campaign));
        """)
        db.execute("INSERT INTO authority VALUES(?)", (namespace,))
        db.executemany("INSERT INTO action VALUES(?,?,'PLANNED',NULL)", actions)
        db.executemany("INSERT INTO binding VALUES(?,?,?)", jobs)


@contextmanager
def transaction(path, namespace):
    # No create, reset, re-enrol or fallback path at runtime.
    uri = Path(path).absolute().as_uri() + "?mode=rw"
    with closing(sqlite3.connect(uri, uri=True, timeout=3)) as db, db:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT namespace FROM authority").fetchall() != [(namespace,)]:
            raise ValueError("AUTHORITY_BINDING")
        yield db


def decide(path, namespace, route, request_sha256, *, recovery):
    """Only a successful committed fresh claim can lead to a dispatch."""
    with transaction(path, namespace) as db:
        row = db.execute("""
            SELECT a.original_id,a.request_sha256,a.state FROM binding b
            JOIN action a ON a.original_id=b.original_id WHERE b.job=? AND b.campaign=?
        """, (route["job"], route["campaign"])).fetchone()
        if row is None:
            raise ValueError("UNREGISTERED_JOB")
        original_id, bound_hash, prior = row
        if original_id != route["original_id"] or bound_hash != request_sha256:
            raise ValueError("ORIGINAL_ACTION_BINDING")
        state, claim = prior, None
        if recovery and prior == "RESERVED":
            state = "UNKNOWN"
        elif not recovery and prior == "PLANNED":
            state, claim = "RESERVED", secrets.token_hex(16)
        if state != prior:
            db.execute("UPDATE action SET state=?,claim=? WHERE original_id=?",
                       (state, claim, original_id))
    return dict(original_id=original_id, prior=prior, state=state, granted=claim is not None,
                claim=claim, recovery=recovery)


def complete(path, namespace, original_id, claim):
    with transaction(path, namespace) as db:
        changed = db.execute("""
            UPDATE action SET state='COMPLETED',claim=NULL
            WHERE original_id=? AND state='RESERVED' AND claim=?
        """, (original_id, claim)).rowcount
        if changed != 1:
            raise ValueError("STALE_COMPLETION")
