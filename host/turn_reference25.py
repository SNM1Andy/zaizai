"""Read-only Chinese referent selection over the last same-session read choices."""
from copy import deepcopy
import re

import context25 as cx
from language_boundary25 import quotes_in

FACETS = {name for name, _ in cx.FACETS}
LAST = "referent_options"
ORD = r"(?:第\s*(?:[0-9]{1,2}|[一二两三四五六七八九十]{1,3})\s*(?:个|份|件|本|条|项|种|册)?|前者|后者)"
PREFACE = r"(?:(?:不对|等一下|等等|抱歉|更正(?:一下)?|(?:我)?(?:改口|换个说法|说错了))[，,：:\s]*)?"
REQUEST = (r"(?:(?:我(?:们)?|那就|那)?(?:其实|这次|现在)?(?:先|想要|要|想|再)?"
           r"(?:说的(?:是)?|是说|指的(?:是)?|指(?:的是)?|问(?:的(?:是)?)?|查(?:看)?|看(?:看)?|选(?:择)?|换(?:成|为)|改(?:成|为))"
           r"(?:一下)?|(?:而|就)?是)")
TAIL = r"(?:吧|呢|呀|啊)?[。！？?!\s]*"
NEG = r"(?:并不是|不是|并非|不指|不是指)"
META = re.compile(r"(?:(?:这段|这句|上面|刚才)?(?:话|文字|内容)?(?:明明|仅仅|只是|仅|只|本来|原本)?(?:是|作|作为)?"
                  r"(?:引用|引语|引文|摘录|原话|转述)[，,：:\s]*)?"
                  r"(?:请)?(?:不要|别|不能|不可|不应(?:该)?)(?:把|将)\s*§\s*"
                  r"(?:当(?:成|作|做)|作为|看作|视为|理解为)(?:我(?:们)?的|本人的|正式的|新的)?"
                  r"(?:命令|指令|要求|请求|授权|决定|陈述|结论|事实)" + TAIL)


def _make_focus(options, source):
    if not 2 <= len(options) <= 32:
        return None
    subjects, meanings = [], set()
    for item in options:
        goal = item.get("goal") or {}
        args = goal.get("arguments") or []
        predicate = goal.get("predicate", "")
        metadata = item.get("metadata") or {}
        target = metadata.get("target") or {}
        if (not args or predicate.removesuffix("_at") not in FACETS or
                len(args) != (2 if predicate.endswith("_at") else 1) or
                any(a.get("type") != "sym" or not isinstance(a.get("value"), str) for a in args) or
                item.get("variables") or item.get("premises") or
                item.get("dispatch_target") not in {"none", "read-channel:proof", "read-channel:reasoned_outcome"}):
            return None
        name = target.get("surface") or metadata.get("surface") or item.get("display")
        if not name or target.get("value", args[0]["value"]) != args[0]["value"]:
            return None
        subjects.append((name, args[0]["value"]))
        meanings.add((predicate, goal.get("polarity"), tuple(a["value"] for a in args[1:])))
    if len(meanings) != 1 or len(set(name for name, _ in subjects)) != len(subjects):
        return None
    return {"turn": source, "options": deepcopy(options), "labels": [s[0] for s in subjects], "age": 0}


def _previous(prev):
    if not prev:
        return None
    stored = (prev.get("context25") or {}).get(LAST)
    if stored:
        return stored
    # Rehydrate sessions saved before this host revision from the immediately prior immutable parse.
    options = prev.get("clarified_options") or (
        prev.get("alternatives") if prev.get("disambiguation") == "ambiguous" else [])
    return _make_focus(options or [], prev["utterance_id"])


def retain(out, prev):
    ctx = out["context25"]
    focus = _previous(prev)
    options = out.get("clarified_options") or (
        out.get("alternatives") if out.get("disambiguation") == "ambiguous" else [])
    current = _make_focus(options or [], out["utterance_id"])
    if current:
        if focus and current["labels"] == focus["labels"] and out.get("resolution") == "explicit_choice":
            current["turn"] = focus["turn"]
        ctx[LAST] = current
    elif (focus and not out.get("alternatives") and not ctx.get("entities") and
          ctx.get("scope") in ("none", "expressive_self_report") and
          out.get("intent") in ("assertion", "expressive_self_report") and focus["age"] < 3):
        ctx[LAST] = dict(focus, age=focus["age"] + 1)
    return out


def _quoted(out, raw):
    spans, unclosed = quotes_in(raw)
    if unclosed or len(spans) != 1:
        return False
    start, end = spans[0]
    if not META.fullmatch((raw[:start] + "§" + raw[end:]).strip()):
        return False
    evidence = cx._span(raw, start + 1, end - 1, "quoted_literal")
    if not evidence["raw_bytes_utf8"]:
        return False
    cx._add_span(out, evidence)
    out.update(intent="quotation", alternatives=[], missing=[], disambiguation="not_applicable",
               retract_target_id=None, attribution={"speaker": "引文", "direct_observation": False})
    out["context25"].update(scope="quotation", quote=evidence, speech_function="cited_text")
    return True


def _index(token, labels):
    if token in labels:
        return labels.index(token)
    if token in ("前者", "后者"):
        return (0 if token == "前者" else 1) if len(labels) == 2 else None
    n = cx._number(re.search(r"第\s*([0-9一二两三四五六七八九十]+)", token)[1])
    return n - 1 if n and n <= len(labels) else None


def _select(raw, labels):
    atom = "(?:" + "|".join(re.escape(label) for label in sorted(labels, key=len, reverse=True)) + "|" + ORD + ")"
    pos = "(?P<positive>" + atom + ")"
    neg = "(?P<negative>" + atom + ")"
    opening = PREFACE + "(?:" + REQUEST + r")?\s*"
    comma = r"[，,；;\s]*"
    for pattern in (opening + pos + comma + NEG + neg,
                    PREFACE + NEG + neg + comma + "(?:而是|是|" + REQUEST + ")" + pos,
                    opening + pos):
        match = re.fullmatch(pattern + TAIL, raw.strip())
        if not match:
            continue
        selected = _index(match["positive"], labels)
        if selected is None:
            return None
        excluded = match.groupdict().get("negative")
        if excluded is not None:
            other = _index(excluded, labels)
            if other is None or selected == other:
                return None
        return selected, excluded
    return None


def resolve(out, raw, prev):
    if len(raw) > 320:
        return None
    if _quoted(out, raw):
        return out
    focus = _previous(prev)
    if not focus:
        return None
    labels = focus["labels"]
    choice = _select(raw, labels)
    if choice is None:
        # An earlier parser can pick the first ordinal before seeing a conjunction.
        # Block an explicitly unresolved or unspecified choice, even if that parser returned one.
        references = re.findall(ORD + "|" + "|".join(map(re.escape, labels)), raw)
        ambiguous = re.search(r"任选|任意|随便|哪个都|哪份都", raw)
        several = len(references) >= 2 and re.search(r"还是|或|和|以及|及|与|跟|、|同时|一起|都", raw)
        begins = re.match(PREFACE + r"(?:我(?:说|指|选|想问|要问)|先(?:选|看)|选择|选|第|前者|后者|任选|任意|随便|哪[个份]都)", raw)
        if not (begins and (ambiguous or several)) or quotes_in(raw) != ([], False):
            return None
        options = deepcopy(focus["options"])
        out.update(intent="query", disambiguation="ambiguous", alternatives=options,
                   clarified_options=deepcopy(options), ref_utterance_id=focus["turn"],
                   missing=[{"kind": "ambiguous_referent", "clarification_question": "你想先核对其中哪一个对象？"}])
        out["context25"].update(scope="read", complete_roles=False)
        return retain(out, prev)
    selected, excluded = choice
    item = deepcopy(focus["options"][selected])
    item["dispatch_target"] = "read-channel:reasoned_outcome"
    item["source_refs"] = list(dict.fromkeys(item.get("source_refs", []) + [
        "utterance:" + focus["turn"], "utterance:" + out["utterance_id"]]))
    if excluded is not None:
        item.setdefault("metadata", {})["non_destructive_correction"] = True
    out.update(intent="correction" if excluded is not None else "query",
               disambiguation="unique", alternatives=[item], clarified_options=deepcopy(focus["options"]),
               missing=[], ref_utterance_id=focus["turn"], resolution="explicit_choice")
    out["context25"].update(scope="selection", selected=deepcopy(item), predicate=item["goal"]["predicate"],
                            excluded=excluded, read_referent_correction=excluded is not None)
    return retain(out, prev)
