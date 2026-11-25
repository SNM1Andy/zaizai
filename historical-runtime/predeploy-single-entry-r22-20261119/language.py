"""Extract the request from the verified CVM message on both routes."""
from common import COMMANDS, PREVIEW, ROOT, digest, need, sha
import r20_routes as r20


def bind(plan, command):
    from al01 import core
    from al01 import folder_contracts as fc

    translated = command == PREVIEW
    need(translated or command in COMMANDS, "COMMAND")
    item = plan["items"][0 if translated else COMMANDS.index(command)]
    expected = item["binding"]
    raw = (ROOT / ("offline.txt" if translated else item["cl_file"])).read_bytes()
    candidate = report = ref = None
    if translated:
        from zhcl_r4 import ZhClPipelineR4
        text = raw.decode("utf8").removesuffix("\n")
        need(command == "中文转译 " + text, "TEXT_COMMAND")
        context = dict(scope_ref=plan["scope_ref"], entries=[
            dict(entry_ref=row["binding"]["request"]["entry_ref"], relative_path=row["name"],
                 kind="file", byte_size=row["object"]["size"]) for row in plan["items"]])
        pipeline = ZhClPipelineR4(context)
        report = pipeline.translate(text)
        need(report["status"] == "OK" and report["text"] == text and
             len(report["candidates"]) == len(report["validation"]) == 1, "TRANSLATION")
        candidate, = report["candidates"]
        validation, = report["validation"]
        req = candidate["request"]
        need(validation["passed"] and not validation["errors"] and validation["checks"]["real_cl"]
             and validation["checks"]["effects_exact"] and
             validation["candidate_id"] == candidate["candidate_id"] == req["request_id"]
             and candidate["entry_ref"] == req["entry_ref"]
             and candidate["provenance"]["origin"] == "ZH_CL_TRANSLATION"
             and candidate["provenance"]["authority"] == "NONE"
             and candidate["candidate_sha256"] == digest({k:v for k,v in candidate.items() if k!="candidate_sha256"})
             and report["counters"]["external_api_calls"] == report["counters"]["receipt_calls"] == 0,
             "TRANSLATION_SOURCE")
        binding = dict(request=req, request_sha256=fc.request_sha256(req))
        r20.check_binding(binding, expected)
        ref = dict(input_sha256=sha(raw), candidate_sha256=candidate["candidate_sha256"])
        route = "offline_translation"
        source = r20.emit_source(dict(format=r20.FORMAT, route=route, translation=ref, **binding))
    else:
        route = "native"
        source = raw.decode("utf8")
    vm = core.CVM(["emit"])
    tx = r20.prepare(vm, source)
    envelope = r20.verify_tx(vm, tx, expected, route, ref)
    return dict(envelope=envelope, input_sha256=sha(raw), cl_sha256=sha(source.encode("utf8")),
                transaction=core.transaction_payload(tx), seal=tx.seal, translation=report,
                cl_version=core.VERSION, registry_version=core.REGISTRY_VERSION)
