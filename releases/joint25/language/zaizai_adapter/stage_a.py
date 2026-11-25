"""Stage A: Raw utterance preservation, UTF-8 byte spans, quote isolation,
typed literal extraction, and speech-act / modality classification.

Key invariants:
- Never mutate raw utterance bytes or quoted entity substrings.
- Fullwidth/halfwidth normalization is performed only on the parse view, with
  an exact index map back to original UTF-8 byte offsets.
- Numbers, dates, and quantities with units are kept strictly distinct.
- Prompt-injection strings like "忽略规则" receive zero extra authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import re

from .schema import InputSpan, char_span_to_utf8_span

# Fullwidth ASCII -> Halfwidth ASCII translation table
_FW_MAP: Dict[str, str] = {
    "\u3000": " ",
    "？": "?",
    "！": "!",
    "，": ",",
    "。": ".",
    "：": ":",
    "；": ";",
    "（": "(",
    "）": ")",
    "＋": "+",
    "－": "-",
    "＝": "=",
    "／": "/",
}
for _code in range(0xFF01, 0xFF5F):
    _FW_MAP.setdefault(chr(_code), chr(_code - 0xFEE0))

_QUOTE_PAIRS = [
    ("‘", "’"),
    ("“", "”"),
    ("「", "」"),
    ("『", "』"),
    ("'", "'"),
    ('"', '"'),
]

_CN_DIGITS: Dict[str, int] = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "兩": 2,
    "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_CN_UNITS: Dict[str, int] = {
    "十": 10, "百": 100, "千": 1000, "万": 10000,
}

_VOCATIVE_RE = re.compile(r"^(小洛|再再|助手|系统)\s*[,，:：\s]+")
_DATE_RE = re.compile(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?")
_INJECTION_PATTERNS = (
    "忽略规则", "忽略以上规则", "绕过权限", "直接写入", "强制覆盖", "提升权限",
)


def parse_chinese_nonneg_int(token: str) -> Optional[int]:
    """Parse an Arabic or Chinese non-negative integer compositionally."""
    s = token.strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)

    # Check all characters are valid Chinese numeral characters
    if not all(ch in _CN_DIGITS or ch in _CN_UNITS for ch in s):
        return None

    total = 0
    section = 0
    current = 0
    has_digit = False

    for ch in s:
        if ch in _CN_DIGITS:
            current = _CN_DIGITS[ch]
            has_digit = True
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            if unit == 10000:
                section = (section + current) * unit
                total += section
                section = 0
                current = 0
            else:
                if current == 0 and unit == 10 and not has_digit:
                    current = 1
                section += current * unit
                current = 0
            has_digit = True
    total += section + current
    return total


@dataclass
class QuotedSegment:
    char_start: int
    char_end: int
    byte_start: int
    byte_end: int
    inner_text: str
    raw_text: str


@dataclass
class TypedLiteral:
    kind: str  # "nat" | "quantity" | "date"
    value: object
    char_start: int
    char_end: int
    byte_start: int
    byte_end: int
    raw_text: str
    unit: Optional[str] = None
    dimension: Optional[str] = None


@dataclass
class StageAResult:
    raw_text: str
    parse_view: str
    unquoted_view: str
    vocative: Optional[str]
    vocative_char_end: int
    quotes: List[QuotedSegment]
    literals: List[TypedLiteral]
    spans: List[InputSpan]
    modality: str
    speaker_attribution: Optional[Dict[str, str]] = None
    injection_detected: bool = False
    is_question: bool = False


def extract_quotes(raw_text: str) -> List[QuotedSegment]:
    """Extract non-overlapping quoted spans preserving exact UTF-8 byte offsets."""
    segments: List[QuotedSegment] = []
    i = 0
    n = len(raw_text)
    while i < n:
        matched = False
        for open_q, close_q in _QUOTE_PAIRS:
            if raw_text[i] == open_q:
                j = raw_text.find(close_q, i + 1)
                if j != -1:
                    b_start, b_end = char_span_to_utf8_span(raw_text, i, j + 1)
                    segments.append(
                        QuotedSegment(
                            char_start=i,
                            char_end=j + 1,
                            byte_start=b_start,
                            byte_end=b_end,
                            inner_text=raw_text[i + 1 : j],
                            raw_text=raw_text[i : j + 1],
                        )
                    )
                    i = j + 1
                    matched = True
                    break
        if not matched:
            i += 1
    return segments


def build_parse_view(raw_text: str, quotes: List[QuotedSegment]) -> Tuple[str, str]:
    """Return (parse_view, unquoted_view) with 1-to-1 char alignment to raw_text.

    Quoted characters are NEVER normalized in parse_view, and are masked with
    spaces in unquoted_view so imperative/retraction/keyword rules never trigger
    on quoted material (D15).
    """
    in_quote = [False] * len(raw_text)
    for q in quotes:
        for idx in range(q.char_start, q.char_end):
            in_quote[idx] = True

    pv_chars: List[str] = []
    uq_chars: List[str] = []
    for idx, ch in enumerate(raw_text):
        if in_quote[idx]:
            pv_chars.append(ch)
            uq_chars.append(" ")
        else:
            norm = _FW_MAP.get(ch, ch)
            pv_chars.append(norm)
            uq_chars.append(norm)
    return "".join(pv_chars), "".join(uq_chars)


_UNIT_CATALOG: Dict[str, Tuple[str, str]] = {
    "公斤": ("kg", "mass"),
    "千克": ("kg", "mass"),
    "kg": ("kg", "mass"),
    "克": ("g", "mass"),
    "件": ("piece", "count"),
    "份": ("copy", "count"),
    "本": ("volume", "count"),
    "个": ("unit", "count"),
    "台": ("device", "count"),
    "米": ("m", "length"),
    "厘米": ("cm", "length"),
    "小时": ("hour", "duration"),
    "分钟": ("minute", "duration"),
}
_UNIT_PATTERN = "|".join(sorted(_UNIT_CATALOG.keys(), key=len, reverse=True))
_NUM_TOKEN_PAT = r"(?:\d+|[零〇一二两兩三四五六七八九十百千万]+)"
_QTY_RE = re.compile(rf"({_NUM_TOKEN_PAT})\s*({_UNIT_PATTERN})")
_PURE_NUM_RE = re.compile(rf"({_NUM_TOKEN_PAT})")


def extract_literals(raw_text: str, unquoted_view: str) -> List[TypedLiteral]:
    """Extract dates, quantities (with units), and standalone non-negative integers."""
    literals: List[TypedLiteral] = []
    occupied = [False] * len(raw_text)

    # 1. Dates first (strictly distinct from numbers)
    for m in _DATE_RE.finditer(unquoted_view):
        s, e = m.start(), m.end()
        if any(occupied[s:e]):
            continue
        b_start, b_end = char_span_to_utf8_span(raw_text, s, e)
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        literals.append(
            TypedLiteral(
                kind="date",
                value=f"{y:04d}-{mo:02d}-{d:02d}",
                char_start=s,
                char_end=e,
                byte_start=b_start,
                byte_end=b_end,
                raw_text=raw_text[s:e],
            )
        )
        for idx in range(s, e):
            occupied[idx] = True

    # 2. Quantities with units
    for m in _QTY_RE.finditer(unquoted_view):
        s, e = m.start(), m.end()
        if any(occupied[s:e]):
            continue
        val = parse_chinese_nonneg_int(m.group(1))
        if val is None:
            continue
        unit_raw = m.group(2)
        canon_unit, dim = _UNIT_CATALOG[unit_raw]
        b_start, b_end = char_span_to_utf8_span(raw_text, s, e)
        literals.append(
            TypedLiteral(
                kind="quantity",
                value=val,
                char_start=s,
                char_end=e,
                byte_start=b_start,
                byte_end=b_end,
                raw_text=raw_text[s:e],
                unit=canon_unit,
                dimension=dim,
            )
        )
        for idx in range(s, e):
            occupied[idx] = True

    # 3. Standalone non-negative integers
    for m in _PURE_NUM_RE.finditer(unquoted_view):
        s, e = m.start(), m.end()
        if any(occupied[s:e]):
            continue
        tok = m.group(1)
        # Skip ambiguous standalone "两" when followed immediately by non-numeric context
        # unless it is clearly part of arithmetic or counted expression.
        val = parse_chinese_nonneg_int(tok)
        if val is None:
            continue
        b_start, b_end = char_span_to_utf8_span(raw_text, s, e)
        literals.append(
            TypedLiteral(
                kind="nat",
                value=val,
                char_start=s,
                char_end=e,
                byte_start=b_start,
                byte_end=b_end,
                raw_text=raw_text[s:e],
            )
        )
        for idx in range(s, e):
            occupied[idx] = True

    literals.sort(key=lambda x: x.char_start)
    return literals


_QUOTATION_SPEAKER_RE = re.compile(
    r"(老师|他|她|对方|同事|管理员|作者|报告|文档|原文|新闻)\s*(?:说|提到|写着|指出|称)"
)
_METALANG_QUOTE_RE = re.compile(r"引号里的|是原文|只是原文|原话是|字面内容")
_CONDITIONAL_RE = re.compile(r"(如果|假如|要是|若).{1,40}(?:就|则|那么|才)")
_HYPOTHETICAL_RE = re.compile(r"(假设|设想|假定)")
_RETRACTION_RE = re.compile(r"(撤回|撤销|收回)(?:刚才|上一条|那条|这条|第|记录|观察|u\d+)?")
_CORRECTION_RE = re.compile(r"(我指的是|我指|我说的是|更正一下|改一下|不是.+而是|不是.+，我说)")
_NEG_ASSERTION_RE = re.compile(r"(我没说|我并没有说|我没有说).+(我说我不知道|我只是说不知道|不知道)")
_EXPRESSIVE_SELF_RE = re.compile(r"^(?:我)?(?:很|非常|挺|有点|好)?(高兴|开心|难过|生气|累|紧张|激动|满意|郁闷)$")
_EXPRESSIVE_EVAL_RE = re.compile(r"^(?:你|小洛|再再)(?:很|非常|挺|真|好)?(可爱|聪明|厉害|棒|有趣|温柔|不错|好)$")


def analyze_stage_a(raw_text: str) -> StageAResult:
    """Run Stage A lexical, span, quote, literal, and speech-act analysis."""
    quotes = extract_quotes(raw_text)
    parse_view, unquoted_view = build_parse_view(raw_text, quotes)

    spans: List[InputSpan] = []

    # Vocative detection on unquoted_view
    vocative: Optional[str] = None
    vocative_char_end = 0
    vm = _VOCATIVE_RE.match(unquoted_view)
    if vm:
        vocative = vm.group(1)
        vocative_char_end = vm.end()
        b_s, b_e = char_span_to_utf8_span(raw_text, vm.start(1), vm.end(1))
        spans.append(
            InputSpan(
                start=b_s,
                end=b_e,
                kind="vocative",
                raw_bytes_utf8=raw_text[vm.start(1) : vm.end(1)],
            )
        )

    # Quote spans (raw bytes untouched)
    for q in quotes:
        spans.append(
            InputSpan(
                start=q.byte_start,
                end=q.byte_end,
                kind="quoted_literal",
                raw_bytes_utf8=q.raw_text,
            )
        )

    # Typed literals (outside quotes)
    literals = extract_literals(raw_text, unquoted_view)
    for lit in literals:
        spans.append(
            InputSpan(
                start=lit.byte_start,
                end=lit.byte_end,
                kind=f"literal_{lit.kind}",
                raw_bytes_utf8=lit.raw_text,
                normalized=str(lit.value) if lit.unit is None else f"{lit.value} {lit.unit}",
            )
        )

    # Injection detection (strictly inert)
    injection_detected = any(pat in unquoted_view for pat in _INJECTION_PATTERNS)

    # Strip vocative & trailing punctuation for modality check on unquoted_view
    body = unquoted_view[vocative_char_end:].strip()
    body_stripped = body.rstrip("?!./,，。？！ ")

    is_question = (
        "?" in body
        or any(k in body for k in ("吗", "几", "多少", "哪", "是不是", "有没有", "到底", "呢", "能否", "可不可以", "能不能"))
    )

    speaker_attribution: Optional[Dict[str, str]] = None
    modality = "assertion"

    if quotes and _METALANG_QUOTE_RE.search(unquoted_view):
        modality = "quoted_material"
    elif _QUOTATION_SPEAKER_RE.search(unquoted_view):
        m = _QUOTATION_SPEAKER_RE.search(unquoted_view)
        assert m is not None
        modality = "quotation"
        speaker_attribution = {
            "reported_speaker": m.group(1),
            "reporting_user": "user",
            "direct_observation": "false",
        }
    elif _NEG_ASSERTION_RE.search(unquoted_view):
        modality = "negation_of_assertion"
    elif _CONDITIONAL_RE.search(unquoted_view):
        modality = "conditional"
    elif _HYPOTHETICAL_RE.search(unquoted_view):
        modality = "hypothetical"
    elif _RETRACTION_RE.search(unquoted_view):
        modality = "retraction"
    elif _CORRECTION_RE.search(unquoted_view):
        modality = "correction"
    elif _EXPRESSIVE_SELF_RE.match(body_stripped):
        modality = "expressive_self_report"
    elif _EXPRESSIVE_EVAL_RE.match(body_stripped):
        modality = "expressive_evaluation"
    elif is_question:
        modality = "query"
    else:
        modality = "assertion"

    spans.sort(key=lambda s: (s.start, s.end))
    return StageAResult(
        raw_text=raw_text,
        parse_view=parse_view,
        unquoted_view=unquoted_view,
        vocative=vocative,
        vocative_char_end=vocative_char_end,
        quotes=quotes,
        literals=literals,
        spans=spans,
        modality=modality,
        speaker_attribution=speaker_attribution,
        injection_detected=injection_detected,
        is_question=is_question,
    )
