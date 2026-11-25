"""Model-free bounded conversation; provider payloads are data, never CL code."""
from dataclasses import dataclass
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import unicodedata

FREEZE_SHA = "fc939c0186b9ef5fc8b1bf9677589f8d9fad3f3f712fc1c81a6624ac86e93b75"
INTENTS = frozenset({"status", "receipt", "greet", "terms", "help"})
BASE = {"状态": "status", "你现在怎么样": "status", "最近回执": "receipt",
        "你好": "greet", "词典": "terms", "帮助": "help"}
TERM = re.compile(r"[a-z][a-z0-9 -]{0,39}|[\u3400-\u9fff]{1,24}")
RECEIPT = re.compile(r"[A-Za-z0-9_-]{1,120}")


def require(ok, error):
    if not ok:
        raise ValueError(error)


def normalized(s):
    require(type(s) is str and 0 < len(s) <= 512, "input must be 1..512 characters")
    s = unicodedata.normalize("NFKC", s).strip().lower().rstrip("?!。！？").strip()
    require(bool(s) and not any(unicodedata.category(c).startswith("C") for c in s),
            "input cannot be empty or contain control characters")
    return s


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(data):
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def load_native(bundle):
    """Import the installed native package from the pinned source set, read-only."""
    bundle = Path(bundle).resolve(strict=True)
    freeze_raw = (bundle / "FREEZE.json").read_bytes()
    require(sha(freeze_raw) == FREEZE_SHA, "unsupported native freeze digest")
    pins = json.loads(freeze_raw)["files"]
    lib = (bundle / "lib").resolve(strict=True)
    directory = (lib / "al01").resolve(strict=True)
    require(directory.parent == lib and lib.parent == bundle, "native library escaped bundle")
    files = {str(p.relative_to(bundle).as_posix()): p for p in directory.glob("*.py")}
    expected = {k: v for k, v in pins.items() if k.startswith("lib/al01/") and k.endswith(".py")}
    require(files.keys() == expected.keys(), "native source set mismatch")
    require(all(p.resolve() == p and sha(p.read_bytes()) == expected[k] for k, p in files.items()),
            "native source digest mismatch")
    require(not any(directory.glob("*.pyc")) and not (directory / "__pycache__").exists(),
            "unexpected native bytecode: use source-only native bundle")
    require(not any(k == "al01" or k.startswith("al01.") for k in sys.modules),
            "load native once in a dedicated runner, not a mixed environment")
    no_pyc = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location(
            "al01", directory / "__init__.py", submodule_search_locations=[str(directory)])
        require(spec is not None and spec.loader is not None, "native package import unavailable")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return sys.modules["al01.core"]
    finally:
        sys.dont_write_bytecode = no_pyc


@dataclass(frozen=True)
class State:
    identity: str
    generation: int
    tick: int
    receipt: str | None
    prior_turns: int

    def __post_init__(self):
        require(type(self.identity) is str and RECEIPT.fullmatch(self.identity),
                "invalid identity")
        require(all(type(n) is int and 0 <= n <= 2**53 for n in
                    (self.generation, self.tick, self.prior_turns)), "invalid state counters")
        require(self.receipt is None or type(self.receipt) is str and RECEIPT.fullmatch(self.receipt),
                "invalid receipt")


@dataclass(frozen=True)
class Lexicon:
    """Aliases are declarative; promotion belongs to the host governance transaction."""
    owner: str
    version: int = 0
    entries: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        require(type(self.owner) is str and RECEIPT.fullmatch(self.owner), "invalid owner")
        require(type(self.version) is int and 0 <= self.version <= 2**53, "invalid lexicon version")
        require(type(self.entries) is tuple and len(self.entries) <= 256, "invalid lexicon size")
        seen = set(BASE)
        for pair in self.entries:
            require(type(pair) is tuple and len(pair) == 2, "invalid lexicon pair")
            word, intent = pair
            require(type(word) is str and TERM.fullmatch(word) and normalized(word) == word and
                    word not in seen and type(intent) is str and intent in INTENTS, "invalid or reserved alias")
            seen.add(word)


def _emit(data):
    # Encode twice: one JSON data envelope, one literal CL Text. No string gets emitted as raw CL.
    # Keep non-BMP Unicode as scalar UTF-8 text, not JSON surrogate escapes.
    return "EMIT(OK(value=" + json.dumps(canonical(data), ensure_ascii=False) + "));"


def _native(core, state, src):
    vm = core.CVM(["emit"])
    tx = vm.prepare(src, {"version": state.generation, "world_version": state.tick}, ())
    vm.verify(tx)
    payload = core.transaction_payload(tx)
    require(not payload["proposals"] and not payload["neuron_calls"] and
            payload["wait_reason"] is None and len(payload["messages"]) == 1, "non-dialogue CVM effects")
    msg, = payload["messages"]
    require(msg.keys() == {"tag", "type", "value"} and msg["tag"] == "OK" and
            msg["type"] == "Result<Text>", "invalid CVM message")
    return json.loads(msg["value"])


def converse(core, state, lexicon, user_input):
    """Return CL/CVM-verified data; never mutate or call a model or external service."""
    require(state.identity == lexicon.owner, "lexicon identity mismatch")
    phrase = normalized(user_input)
    intent = (BASE | dict(lexicon.entries)).get(phrase)
    common = {"schema": "zaizai.cl.dialogue.v1", "lexicon_version": lexicon.version, "intent": intent}

    def reply(text, gap=None):
        return _emit(dict(common, reply=text, gap=gap))

    if intent == "status":
        src = reply(f"我在第 {state.generation} 代，运行到 tick {state.tick}。")
    elif intent == "receipt":
        src = reply("我没有已保存回执。" if state.receipt is None else
                    f"我的最近回执是 {state.receipt}。")
    elif intent == "greet":
        src = f"IF GT({state.prior_turns},0) {{ " + reply("你回来啦。") + "} ELSE {" + reply("你好，我是再再。") + "}"
    elif intent == "terms":
        src = reply(f"我现在有 {len(BASE)} 个内置用语和 {len(lexicon.entries)} 个扩展用语。")
    elif intent == "help":
        src = reply("我能用 CL 回答状态、最近回执和词典；不懂的表达会请你澄清。")
    else:
        # Hash only leaves the gap API; a host must separately authorize sharing user text.
        gap = {"schema":"zaizai.cl.gap.v1", "id":sha(canonical({
            "identity":state.identity,"version":lexicon.version,"phrase":phrase}).encode()),
            "request":"alias_mapping", "supported_intents":sorted(INTENTS)}
        src = reply("这个说法我还不懂。你是在问我的状态、回执，还是别的事情？", gap)
    return _native(core, state, src)


def decode_advice(raw):
    """Adapter-neutral wire contract; never connects to DeepSeek or DSH on its own."""
    require(type(raw) is bytes and 0 < len(raw) <= 4096, "advice payload size")

    def unique(pairs):
        obj = dict(pairs)
        require(len(obj) == len(pairs), "duplicate advice field")
        return obj

    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("invalid advice JSON") from exc
    require(type(data) is dict and data.keys() == {"schema", "gap_id", "kind", "alias", "intent"}
            and data["schema"] == "zaizai.cl.advice.v1", "advice schema")
    require(type(data["kind"]) is str and data["kind"] in {"translation","lexicon_suggestion"},
            "unsupported advice kind")
    require(type(data["gap_id"]) is str and re.fullmatch(r"[0-9a-f]{64}", data["gap_id"]),
            "invalid advice gap id")
    require(type(data["alias"]) is str and TERM.fullmatch(data["alias"]) and
            type(data["intent"]) is str and data["intent"] in INTENTS, "invalid advice alias or intent")
    return data


def assess_advice(core, state, lexicon, original_input, raw):
    """Local verification; both advice kinds return a candidate, not an accepted translation."""
    advice = decode_advice(raw)
    original = converse(core, state, lexicon, original_input)
    require(original["gap"] is not None and original["gap"]["id"] == advice["gap_id"], "unknown or stale gap")
    require(normalized(original_input) == advice["alias"], "alias does not match observed gap")
    candidate = Lexicon(lexicon.owner,lexicon.version + 1,lexicon.entries + ((advice["alias"],advice["intent"]),))
    trial = converse(core, state, candidate, original_input)
    require(trial["gap"] is None and trial["intent"] == advice["intent"], "candidate did not resolve gap")
    return {"schema":"zaizai.cl.candidate.v1","origin":"external_advice","authority":"none",
            "adopted":False,"base_version":lexicon.version,"gap_id":advice["gap_id"],
            "alias":advice["alias"],"intent":advice["intent"]}

