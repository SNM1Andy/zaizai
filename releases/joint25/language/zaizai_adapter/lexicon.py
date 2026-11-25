"""Versioned lexicon loader compatible with cl-lexicon-sense-v1 fixtures.

Important:
- `demo.*` senses are strictly for development fixtures and MUST NOT enter any
  production dictionary.
- Missing, mismatched, or unverified lexicon versions fail closed with
  `LexiconVersionError` instead of silently falling back or inventing senses.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import json

from .schema import LEXICON_SCHEMA


class LexiconVersionError(RuntimeError):
    """Raised when a requested lexicon version is missing, malformed, or mismatched."""


@dataclass(frozen=True)
class SenseEntry:
    sense_id: str
    kind: str  # "predicate" | "entity" | "operator" | "unit" | "concept"
    canonical: str
    surface_forms: Tuple[str, ...]
    arg_types: Tuple[str, ...] = ()
    status: str = "reviewed"  # "reviewed" | "candidate"
    dimension: Optional[str] = None
    notes: str = ""


class Lexicon:
    def __init__(
        self,
        version: str,
        entries: List[SenseEntry],
        allow_candidate_layer: bool = False,
        source_path: Optional[str] = None,
    ) -> None:
        self.version = version
        self.allow_candidate_layer = allow_candidate_layer
        self.source_path = source_path
        self._by_id: Dict[str, SenseEntry] = {}
        self._by_surface: Dict[str, List[SenseEntry]] = {}
        self._by_canonical: Dict[str, List[SenseEntry]] = {}

        for entry in entries:
            if entry.status != "reviewed" and not allow_candidate_layer:
                continue
            self._by_id[entry.sense_id] = entry
            self._by_canonical.setdefault(entry.canonical, []).append(entry)
            for form in entry.surface_forms:
                self._by_surface.setdefault(form, []).append(entry)

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        expected_version: Optional[str] = None,
        allow_candidate_layer: bool = False,
    ) -> "Lexicon":
        p = Path(path)
        if not p.exists():
            raise LexiconVersionError(f"Lexicon file not found: {p}")
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            raise LexiconVersionError(f"Malformed lexicon JSON at {p}: {exc}") from exc

        schema = raw.get("schema")
        if schema != LEXICON_SCHEMA:
            raise LexiconVersionError(
                f"Invalid lexicon schema '{schema}'; expected '{LEXICON_SCHEMA}'"
            )
        version = raw.get("lexicon_version")
        if not isinstance(version, str) or not version.strip():
            raise LexiconVersionError("Lexicon missing non-empty 'lexicon_version'")
        if expected_version is not None and version != expected_version:
            raise LexiconVersionError(
                f"Lexicon version mismatch: expected '{expected_version}', got '{version}'"
            )

        raw_entries = raw.get("entries")
        if not isinstance(raw_entries, list):
            raise LexiconVersionError("Lexicon 'entries' must be a list")

        entries: List[SenseEntry] = []
        seen_ids: Set[str] = set()
        for item in raw_entries:
            sid = item.get("sense_id")
            if not sid or sid in seen_ids:
                raise LexiconVersionError(f"Duplicate or missing sense_id: {sid}")
            seen_ids.add(sid)
            entries.append(
                SenseEntry(
                    sense_id=sid,
                    kind=item["kind"],
                    canonical=item["canonical"],
                    surface_forms=tuple(item.get("surface_forms", [])),
                    arg_types=tuple(item.get("arg_types", [])),
                    status=item.get("status", "reviewed"),
                    dimension=item.get("dimension"),
                    notes=item.get("notes", ""),
                )
            )
        return cls(
            version=version,
            entries=entries,
            allow_candidate_layer=allow_candidate_layer,
            source_path=str(p),
        )

    def get_by_id(self, sense_id: str) -> Optional[SenseEntry]:
        return self._by_id.get(sense_id)

    def lookup_surface(self, surface: str, kind: Optional[str] = None) -> List[SenseEntry]:
        matches = self._by_surface.get(surface, [])
        if kind is not None:
            return [m for m in matches if m.kind == kind]
        return list(matches)

    def all_entries(self, kind: Optional[str] = None) -> List[SenseEntry]:
        if kind is None:
            return list(self._by_id.values())
        return [e for e in self._by_id.values() if e.kind == kind]

    def surface_forms_by_length(self, kind: Optional[str] = None) -> List[Tuple[str, List[SenseEntry]]]:
        items: List[Tuple[str, List[SenseEntry]]] = []
        for form, entries in self._by_surface.items():
            filtered = [e for e in entries if kind is None or e.kind == kind]
            if filtered:
                items.append((form, filtered))
        items.sort(key=lambda kv: len(kv[0]), reverse=True)
        return items


class LexiconRegistry:
    """Holds multiple pinned lexicon versions so historical turns never drift."""

    def __init__(self) -> None:
        self._versions: Dict[str, Lexicon] = {}

    def register(self, lexicon: Lexicon) -> None:
        self._versions[lexicon.version] = lexicon

    def register_file(
        self,
        path: str | Path,
        expected_version: Optional[str] = None,
        allow_candidate_layer: bool = False,
    ) -> Lexicon:
        lex = Lexicon.from_file(
            path,
            expected_version=expected_version,
            allow_candidate_layer=allow_candidate_layer,
        )
        self.register(lex)
        return lex

    def get(self, version: str) -> Lexicon:
        if version not in self._versions:
            raise LexiconVersionError(
                f"Requested lexicon version '{version}' is not registered. "
                f"Available: {sorted(self._versions.keys())}"
            )
        return self._versions[version]

    def has(self, version: str) -> bool:
        return version in self._versions
