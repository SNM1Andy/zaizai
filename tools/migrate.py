"""Import the installed 1.0 snapshot and verify every original row and byte."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]
INSTALL = Path(os.environ.get("ZAIZAI_LEGACY_INSTALL") or (ROOT.parent/"Zaizai"/"INSTALL.json"))
EXPECTED_FIELDS = ["seq", "identity", "request", "response", "build"]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inventory(directory):
    return {p.relative_to(directory).as_posix(): digest(p)
            for p in directory.rglob("*") if p.is_file()}


def check(condition, detail):
    if not condition:
        raise ValueError(detail)


def row_digest(rows):
    raw = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def connection(path):
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def migrate():
    config = json.loads(INSTALL.read_bytes())
    check(config["version"] == "zaizai-local-1.0", "Unknown 1.0 save version")
    source = Path(config["nativeStateReadOnly"])
    ui = Path(config["conversationData"])
    files = inventory(source)
    identity = config["activeIdentity"]
    anchor = json.loads((source / "joint-reopen.json").read_bytes())
    check(anchor["identity"] == identity and anchor["receipt"] == config["lastSavedM5Receipt"],
          "Checkpoint does not belong to the installed identity or M5 receipt")
    out = ROOT / "state"
    with closing(connection(ui)) as db:
        db.execute("BEGIN")
        check(db.execute("PRAGMA quick_check").fetchall() == [("ok",)], "Source database corrupt")
        cols = [r[1] for r in db.execute("PRAGMA table_info(turns)")]
        check(cols[:5] == EXPECTED_FIELDS, "Unsupported turn layout")
        rows = db.execute("SELECT * FROM turns ORDER BY seq").fetchall()
        check(all(row[1] == identity for row in rows), "Mixed identity in 1.0 history")
        before = digest(ui)
        if not out.exists():
            stage = Path(tempfile.mkdtemp(prefix="import-", dir=ROOT))
            shutil.copytree(source, stage / "native")
            with closing(sqlite3.connect(stage / ui.name)) as target:
                db.backup(target)
            check(inventory(stage / "native") == files, "Native snapshot copy differs")
            with closing(connection(stage / ui.name)) as target:
                check(target.execute("SELECT * FROM turns ORDER BY seq").fetchall() == rows,
                      "Copied conversation differs")
            check(before == digest(ui) and files == inventory(source), "Source changed during import")
            os.rename(stage, out)
        with closing(connection(out / ui.name)) as target:
            saved = target.execute("SELECT * FROM turns WHERE seq<=? ORDER BY seq",
                                   (rows[-1][0] if rows else 0,)).fetchall()
            check(saved == rows, "Original history differs after migration")
        check(inventory(out / "native") == files and before == digest(ui), "Archive changed")
    info = dict(identity=identity, generation=anchor["generation"], receipt=anchor["receipt"],
                migrated_turns=len(rows), original_seq=[r[0] for r in rows],
                source_history_sha256=before, history_content_sha256=row_digest(rows),
                source_rows_equal_target=True, legacy_native_files=files, columns=cols,
                mapping={"native":"unchanged full tree, including unknown files",
                         "conversation":"SQLite Backup API, all columns, tables and indices"},
                version=config["version"], source=str(ui), target=str(out / ui.name))
    (ROOT / "evidence" / "migration.json").write_text(json.dumps(info, indent=2), encoding="utf8")
    print(f"{identity} | {len(rows)} turns | {len(files)} native files | {row_digest(rows)}")


if __name__ == "__main__":
    migrate()
