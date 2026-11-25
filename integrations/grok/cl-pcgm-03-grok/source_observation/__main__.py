"""Adapter entry: python -m source_observation --fixture PATH

Writes candidate JSONL only. A zero exit means the adapter finished. It does
not mean the case was admitted and it does not write PCGM.
"""

import argparse
import sys
from pathlib import Path

from .adapter import (
    FixtureBoundError,
    adapt_case,
    candidate_bytes,
    failure_bytes,
    load_fixture,
    refuse_source_write,
)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="source_observation")
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--candidates", default="-")
    parser.add_argument("--failures", default="")
    args = parser.parse_args(argv)
    try:
        case = load_fixture(args.fixture)
        result = adapt_case(case)
    except FixtureBoundError as exc:
        sys.stderr.write("fixture bound: %s\n" % exc)
        return 2
    except (OSError, ValueError, KeyError, TypeError) as exc:
        sys.stderr.write("fixture error: %s\n" % exc)
        return 2
    payload = candidate_bytes(result.candidates)
    try:
        if args.candidates == "-":
            sys.stdout.buffer.write(payload)
        else:
            out = Path(args.candidates)
            refuse_source_write(out)
            out.write_bytes(payload)
        if args.failures:
            dest = Path(args.failures)
            refuse_source_write(dest)
            dest.write_bytes(failure_bytes(result.failures))
    except PermissionError as exc:
        sys.stderr.write("refusing write: %s\n" % exc)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
