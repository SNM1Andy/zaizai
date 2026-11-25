"""Repeat the 1.0 import and initialization with copies of the installed host and engines."""
from pathlib import Path
import json
import migrate
import shutil
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
def main():
    with tempfile.TemporaryDirectory(prefix="zaizai-migration-") as scratch:
        stage=Path(scratch).resolve()
        (stage/"evidence").mkdir()
        (stage/"tools").mkdir()
        shutil.copyfile(ROOT/"tools/cold_read.py",stage/"tools/cold_read.py")
        shutil.copytree(ROOT/"host",stage/"host",ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT/"bin",stage/"bin")
        migrate.ROOT=stage
        migrate.migrate()
        sys.path.insert(0,str(stage/"host"))
        import native as n
        n.PYTHON=ROOT/"runtime/python.exe"
        first=n.initialize()
        proof=n.proof_for("r28_remembers(object_0000)")
        assert proof["proof"]["results"][0]["status"]=="POSITIVE"
        head=n.sha(n.SAVE.read_bytes())
        marker=(n.STATE/"imported.json").read_bytes()
        # Only the disposable result loses this file, modelling an interruption after native import.
        (n.STATE/"imported.json").unlink()
        second=n.initialize()
        assert first["identity"]==second["identity"] and head==n.sha(n.SAVE.read_bytes())
        assert (n.STATE/"imported.json").read_bytes()==marker
        (ROOT/"evidence/fresh-import.json").write_text(n.canonical(dict(identity=first["identity"],
            same_head_after_restart=True,recovered_import_marker=True,source_proof=proof["integrity"],
            original_semantic_memory_count=len(n.legacy_memory.overview()["memory_targets"]))),encoding="utf8")
        print("Fresh install, original memory, interrupted import marker and restart verified")
if __name__=="__main__":main()
