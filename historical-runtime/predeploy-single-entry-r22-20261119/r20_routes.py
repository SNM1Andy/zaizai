"""R20 local preflight, one route per fresh isolated Python process."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
LIB = ROOT / "lib"
FORMAT = "R20-CL-REQUEST-1"


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def objsha(obj):
    return sha(canonical(obj).encode())


def unique(pairs):
    obj = dict(pairs)
    need(len(obj) == len(pairs), "duplicate JSON key")
    return obj


def parse(raw):
    return json.loads(raw, object_pairs_hook=unique)


def emit_source(envelope):
    return "EMIT(OK(value=" + json.dumps(canonical(envelope)) + "));"


def warmup(route, pins):
    sys.path.insert(0, str(LIB))
    from al01 import core, folder_contracts, sum_types, references
    if route == "offline_translation":
        from zhcl_r4 import ZhClPipelineR4
        from zhcl import candidates, validate_cl, cl_imports
    modules = {k: Path(v.__file__).resolve() for k, v in sys.modules.items()
               if k.split(".")[0] in ("zhcl", "zhcl_r4", "al01")}
    for path in modules.values():
        name = path.relative_to(ROOT).as_posix()
        need(name in pins and sha(path.read_bytes()) == pins[name], "loaded source mismatch")
    need(any(k.startswith("zhcl") for k in modules) == (route == "offline_translation"), "mixed route")
    return sorted(modules)


def check_binding(data, expected):
    from al01 import folder_contracts as fc
    need(type(data) is dict and data.keys() == {"request", "request_sha256"}, "binding fields")
    req = data["request"]
    fc.validate_request(req)
    need(fc.request_sha256(req) == data["request_sha256"] == objsha(req), "request digest")
    need(canonical(req) == canonical(expected["request"]), "different frozen request")
    need(data["request_sha256"] == expected["request_sha256"], "different frozen digest")
    return req


def verify_tx(vm, tx, expected, route, translation_ref=None):
    from al01 import core
    vm.verify(tx)
    payload = core.transaction_payload(tx)
    need(not payload["proposals"] and not payload["neuron_calls"] and payload["wait_reason"] is None
         and len(payload["messages"]) == 1, "unexpected CVM effects")
    msg, = payload["messages"]
    need(msg.keys() == {"tag", "type", "value"} and msg["tag"] == "OK" and msg["type"] == "Result<Text>",
         "message contract")
    need(isinstance(msg["value"], str) and msg["value"].startswith("{"), "full route envelope required")
    env = parse(msg["value"])
    need(canonical(env) == msg["value"], "noncanonical message")
    need(type(env) is dict and env.get("route") == route and env.get("format") == FORMAT, "route/format")
    fields = {"route", "format", "request", "request_sha256"}
    if route == "offline_translation":
        fields.add("translation")
        need(env.get("translation") == translation_ref and translation_ref is not None, "translation source")
    need(env.keys() == fields, "envelope fields")
    check_binding({k: env[k] for k in ("request", "request_sha256")}, expected)
    return env


def prepare(vm, source):
    return vm.prepare(source, {"version": 0, "world_version": 0}, ())


def offline_input(raw, expected):
    from zhcl_r4 import ZhClPipelineR4
    from al01 import folder_contracts as fc
    pipe = ZhClPipelineR4({"scope_ref": expected["request"]["scope_ref"], "entries": []})
    text = raw.decode().removesuffix("\n")
    proposal = pipe.translate(text)
    need(proposal["text"] == text == "列出目录" and proposal["status"] == "OK", "translation input")
    candidate, = proposal["candidates"]
    record, = proposal["validation"]
    need(record["passed"] and record["candidate_id"] == candidate["candidate_id"] and not record["errors"]
         and record["checks"]["real_cl"] and record["checks"]["effects_exact"], "translation validation")
    need(candidate["provenance"]["origin"] == "ZH_CL_TRANSLATION" and candidate["provenance"]["authority"] == "NONE"
         and candidate["candidate_sha256"] == objsha({k: v for k, v in candidate.items() if k != "candidate_sha256"}),
         "translation provenance")
    req = candidate["request"]
    need(candidate["operation"] == req["operation"] and candidate["candidate_id"] == req["request_id"],
         "translation candidate binding")
    binding = {"request": req, "request_sha256": fc.request_sha256(req)}
    check_binding(binding, expected)
    ref = {"input_sha256": sha(raw), "candidate_sha256": candidate["candidate_sha256"]}
    env = dict(format=FORMAT, route="offline_translation", translation=ref, **binding)
    need(pipe.counters["receipt_calls"] == pipe.counters["external_api_calls"] == 0, "translation boundary")
    return emit_source(env), ref, proposal


def negatives(vm, tx, envelope, expected, route, ref):
    from al01 import core
    from al01.folder_contracts import FolderContractError
    results = {}

    def reject(name, fn, exception, message):
        try:
            fn()
        except exception as exc:
            need(str(exc) == message, "unexpected rejection " + name + ": " + str(exc))
            results[name] = str(exc)
            return
        raise AssertionError("accepted " + name)

    def changed(name, edit, reason, exc=ValueError, rehash=True):
        # Prepare/verify a genuine, newly sealed transaction for the altered message.
        other = copy.deepcopy(envelope)
        edit(other)
        if rehash:
            other["request_sha256"] = objsha(other["request"])
        altered = prepare(vm, emit_source(other))
        reject(name, lambda: verify_tx(vm, altered, expected, route, ref), exc, reason)

    for field, value in (("scope_ref", "scope_" + "f" * 32), ("request_id", "req_" + "f" * 32),
                         ("entry_ref", "entry_" + "f" * 32)):
        changed(field, lambda env: env["request"].update({field: value}), "different frozen request")
    for limit in ("max_depth", "max_entries", "max_text_bytes"):
        changed(limit, lambda env: env["request"]["limits"].update({limit: 1}), "fixed safe budgets", FolderContractError)
    changed("wrong_digest", lambda env: env.update(request_sha256="0"*64), "request digest", rehash=False)
    changed("operation", lambda env: env["request"].update(operation="READ_TEXT", entry_ref="entry_"+"f"*32),
            "different frozen request")
    changed("schema", lambda env: env["request"].update(schema="other"), "request schema", FolderContractError)
    changed("route", lambda env: env.update(route="offline_translation" if route == "native" else "native"),
            "route/format")
    if ref is not None:
        changed("candidate_digest", lambda env: env["translation"].update(candidate_sha256="0"*64),
                "translation source")
    legacy = prepare(vm, 'EMIT(OK(value="LIST_SCOPE"));')
    reject("operation_only_CL", lambda: verify_tx(vm, legacy, expected, route, ref),
           ValueError, "full route envelope required")
    rejected = copy.deepcopy(tx)
    rejected.messages[0]["value"] += " "
    reject("post_seal_edit", lambda: verify_tx(vm, rejected, expected, route, ref), core.CLError,
           "TRANSACTION_INVALID: modified or unissued transaction")
    return results


def main():
    need(len(sys.argv) == 3 and sys.argv[1] in ("native", "offline_translation"), "route and freeze pin required")
    route, pin = sys.argv[1:]
    need(sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode and not sys.flags.optimize,
         "use -I -S -B")
    freeze = (ROOT / "release.json").read_bytes()
    need(sha(freeze) == pin, "release mismatch")
    files = parse(freeze)["files"]
    for name in ("routes.py", "expected.json", "language-dependencies.json", "direct.cl" if route == "native" else "offline.txt"):
        need(sha((ROOT / name).read_bytes()) == files[name], "changed " + name)
    manifest = parse((ROOT / "language-dependencies.json").read_bytes())
    need(sha(Path(sys.executable).read_bytes()) == manifest["python_sha256"], "python image")
    pins = manifest["files"]
    need({p.relative_to(ROOT).as_posix() for p in LIB.rglob("*") if p.is_file()} == set(pins), "language tree")
    for name, expected_pin in pins.items():
        path = ROOT / name
        need(path.resolve() == path and sha(path.read_bytes()) == expected_pin, "language dependency " + name)
    raw = (ROOT / ("direct.cl" if route == "native" else "offline.txt")).read_bytes()
    expected = parse((ROOT / "expected.json").read_bytes())
    modules = warmup(route, pins)
    from al01 import core
    blocked = []

    def audit(event, args):
        if event in {"open", "subprocess.Popen", "os.system", "os.listdir", "os.scandir",
                     "sqlite3.connect", "os.remove", "os.rename", "os.mkdir", "os.rmdir", "os.chmod",
                     "os.startfile", "os.spawn"} or event.startswith(("socket.", "winreg.", "ctypes.")):
            blocked.append(event)
            raise PermissionError("preflight boundary " + event)

    sys.addaudithook(audit)
    ref = translation = None
    if route == "native":
        source = raw.decode()
    else:
        source, ref, translation = offline_input(raw, expected)
    vm = core.CVM(["emit"])
    tx = prepare(vm, source)
    envelope = verify_tx(vm, tx, expected, route, ref)
    cases = negatives(vm, tx, envelope, expected, route, ref)
    need(not blocked, "forbidden event observed")
    print(canonical(dict(route=route, pid=os.getpid(), release_sha256=pin, input_sha256=sha(raw),
                         modules=modules, cl_version=core.VERSION, registry_version=core.REGISTRY_VERSION,
                         envelope=envelope, sealed_transaction=core.transaction_payload(tx),
                         transaction_seal=tx.seal, translation=translation, negatives=cases,
                         forbidden_events=blocked, status="VERIFIED_DRY_BINDING")))


if __name__ == "__main__":
    main()
