"""Load the shipped 38-case classifier.

Family counts and four-values stay in that module. This package calls it.
It does not copy the rules and it does not rewrite the historical cases.
"""

import importlib.util
from pathlib import Path

_PROVENANCE = (
    Path(__file__).resolve().parents[2]
    / "zaizai-source-provenance"
    / "test_source_provenance.py"
)

_MODULE = None


def provenance_path():
    return _PROVENANCE


def shipped_module():
    global _MODULE
    if _MODULE is None:
        if not _PROVENANCE.is_file():
            raise FileNotFoundError(
                "shipped provenance checker is missing: %s" % _PROVENANCE
            )
        spec = importlib.util.spec_from_file_location(
            "zaizai_source_provenance_shipped", _PROVENANCE
        )
        if spec is None or spec.loader is None:
            raise ImportError("cannot load shipped provenance checker")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _MODULE = module
    return _MODULE
