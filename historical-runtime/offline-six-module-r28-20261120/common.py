"""Shared helpers for the fixed R21 development fixture, with no production route."""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"
DB = ROOT / "one-shot.sqlite"
NAMES = ("question-1.txt",)
COMMANDS = tuple("读取 " + name for name in NAMES)
PREVIEW = "中文转译 " + COMMANDS[0]
MODE = "R28_OFFLINE_SYNTHETIC_DEVELOPMENT_ONLY"
# Test confirmation is local to this package. No coordinator identity is asserted.
TEST_SOURCE = "local_operator_unverified"
PYTHON_SHA = "50f885251e42eb8cd1fbf5d4fbcc01efdbe8b9f4d4379e16664d4d0f3d4a9869"


class Refused(ValueError):
    pass


def need(ok, reason):
    if not ok:
        raise Refused(reason)


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(obj):
    return sha(canonical(obj).encode("utf8"))


def unique(pairs):
    obj = dict(pairs)
    need(len(pairs) == len(obj), "DUPLICATE_KEY")
    return obj


def parse(raw):
    return json.loads(raw, object_pairs_hook=unique)


def stdin_json():
    raw = sys.stdin.buffer.read(65537)
    need(0 < len(raw) <= 65536, "WIRE_BOUND")
    return parse(raw.decode("utf8"))


def put(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def json_file(name, obj):
    put(ROOT / name, (canonical(obj) + "\n").encode("utf8"))


def verify_release(pin):
    need(sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode and not sys.flags.optimize,
         "INTERPRETER_FLAGS")
    raw = (ROOT / "release.json").read_bytes()
    need(sha(raw) == pin and sha(Path(sys.executable).read_bytes()) == PYTHON_SHA, "RELEASE_OR_IMAGE")
    release = parse(raw)
    need(release["mode"] == MODE, "RELEASE_MODE")
    for name, expected in release["files"].items():
        path = ROOT / name
        need(path.resolve() == path and path.is_relative_to(ROOT) and sha(path.read_bytes()) == expected,
             "RELEASE_MEMBER")
    lib = ROOT / "r14/bundle/lib"
    expected_lib = {n for n in release["files"] if n.startswith("r14/bundle/lib/")}
    actual_lib = {p.relative_to(ROOT).as_posix() for p in lib.rglob("*") if p.is_file()}
    need(expected_lib == actual_lib, "LANGUAGE_TREE")
    actual_code = {p.name for p in ROOT.glob("*.py")}
    bundled = {p.relative_to(ROOT).as_posix() for p in (ROOT / "r14").rglob("*") if p.is_file()}
    need(actual_code == {n for n in release["files"] if "/" not in n and n.endswith(".py")}
         and bundled == {n for n in release["files"] if n.startswith("r14/")}, "CODE_SET")
    sys.path.insert(0, str(lib))
    return parse((ROOT / "plan.json").read_bytes())


def db_open(pin, readonly=False):
    # Never create a replacement for a missing or uncertain ledger.
    db = sqlite3.connect(DB.as_uri() + ("?mode=ro" if readonly else "?mode=rw"),
                         uri=True, timeout=5, isolation_level=None)
    db.row_factory = sqlite3.Row
    need(db.execute("SELECT release_sha FROM campaign").fetchone()[0] == pin, "LEDGER_RELEASE")
    return db


def fingerprint(info):
    return dict(volume=info.st_dev, file_id=str(info.st_ino), size=info.st_size,
                mtime_ns=info.st_mtime_ns)


def regular(info):
    need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_ino != 0
         and not info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT, "UNSAFE_FILE")


def argv(script, pin):
    return [sys.executable, "-X", "utf8", "-I", "-S", "-B", str(ROOT / "entry.py"), {"backend_api.py":"api", "m2_reader.py":"reader"}[script], pin]


def child(script, pin):
    return subprocess.Popen(argv(script, pin), cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, close_fds=True, env={"SystemRoot": os.environ["SystemRoot"]},
                            creationflags=subprocess.CREATE_NO_WINDOW)


def fields(obj, names):
    need(type(obj) is dict and set(obj) == set(names.split()), "WIRE_FIELDS")


def nonce_ok(nonce):
    return type(nonce) is str and re.fullmatch("[0-9a-f]{32}", nonce) is not None
