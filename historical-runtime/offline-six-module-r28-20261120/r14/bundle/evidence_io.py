"""Small read-only primitives shared by the cold reader and the history control."""
import hashlib
import json
from pathlib import PureWindowsPath
import re
import stat


class Rejected(ValueError):
    pass


def require(ok, why):
    if not ok:
        raise Rejected(why)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
                      allow_nan=False).encode("utf-8")


def digest(value):
    return sha(encode(value))


def same(a, b, why):
    # JSON/Python equality alone equates False with the integer zero.
    require(encode(a) == encode(b), why)


def decode(raw):
    def unique(items):
        obj = dict(items)
        require(len(obj) == len(items), "duplicate JSON key")
        return obj

    def invalid(value):
        raise Rejected("nonfinite JSON number")

    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=invalid)


def hexsha(value):
    require(isinstance(value, str) and re.fullmatch("[a-f0-9]{64}", value), "invalid SHA256")
    return value


def relative(name):
    require(isinstance(name, str) and len(name) <= 400, "invalid relative path")
    for part in name.split("/"):
        require(re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9._-]*", part) and not part.endswith(".")
                and not PureWindowsPath(part).is_reserved(), "unsafe path component")
    return name


def plain(path, *, directory=False):
    for p in (*reversed(path.parents), path):
        info = p.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0)
                & stat.FILE_ATTRIBUTE_REPARSE_POINT, "linked evidence path")
    if directory:
        require(stat.S_ISDIR(info.st_mode), "expected directory")
    else:
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "expected single-link file")
    return path


def read(root, name, pin=None):
    path = plain(root / relative(name))
    with path.open("rb") as stream:
        raw = stream.read(16 * 1024 * 1024 + 1)
    require(len(raw) <= 16 * 1024 * 1024, "size limit")
    if pin is not None:
        require(sha(raw) == hexsha(pin), "file digest " + name)
    return raw


def frame(root, name):
    raw = read(root, name)
    wrap = decode(raw)
    same(sorted(wrap), ["data", "sha256"], "frame keys")
    same(digest(wrap["data"]), wrap["sha256"], "frame checksum")
    return wrap["data"], sha(raw)
