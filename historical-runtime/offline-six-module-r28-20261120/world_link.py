"""Fixed translation from the amber world's approved observation to one fixture job."""
from contextlib import closing
import sqlite3

from common import COMMANDS, ROOT, digest, fields, need, parse, sha

RUN = ROOT / "run"
LIVE = RUN / "world/joint.json"
BIRTH = RUN / "birth-joint.json"
DECISION = RUN / "decision-joint.json"


def frame(path):
    raw = path.read_bytes()
    wrap = parse(raw)
    fields(wrap, "data sha256")
    need(digest(wrap["data"]) == wrap["sha256"], "WORLD_FRAME")
    return wrap, sha(raw)


def select(data, plan):
    core = data["core_joint"]
    state = core["individual"]["state"]
    need(state["id"] == plan["identity"] and state["tick"] == data["generation"] == 4
         and core["phase"] == "READY" and not state["requested_actions"], "DECISION_STAGE")
    events = state["events"]
    need([e["kind"] for e in events] == ["commit","feedback"] * 2, "WORLD_SEQUENCE")
    first, last = core["decision_traces"]
    gov = data["modules"]["governance"][1]["arbitration"]
    selected = last["selected"]
    need(first["selected"] == events[1]["payload"]["target"] == "object_0000"
         and events[1]["payload"]["value"] == 1
         and last["source_event_head"] == events[1]["hash"] and last["source_tick"] == 2
         and gov["status"] == "APPROVED" and gov["action_id"] == selected
         and selected == events[3]["payload"]["target"] == plan["route_target"]
         and last["action_id"] == events[2]["payload"]["action_requested"]["action_id"]
         == events[3]["payload"]["action_id"], "NO_MATCHING_WORLD_POLICY")
    return dict(source_observation=events[1]["hash"], selected=selected,
                world_action=last["action_id"], commit_head=events[2]["hash"],
                feedback_head=events[3]["hash"], command=COMMANDS[0],
                folder_request=plan["items"][0]["binding"]["request_sha256"])


def decision(plan, pin, *, live=False):
    birth = parse((RUN / "birth.json").read_bytes())
    born, birth_sha = frame(BIRTH)
    need(birth["identity"] == born["data"]["core_joint"]["individual"]["state"]["id"] == plan["identity"]
         and birth["release"] == pin and birth["tick"] == born["data"]["generation"] == 0
         and birth["phase"] == born["data"]["core_joint"]["phase"] == "READY"
         and birth_sha == birth["joint_sha256"], "BIRTH_BINDING")
    checkpoint, joint_sha = frame(DECISION)
    route = select(checkpoint["data"], plan)
    if live:
        need(sha(LIVE.read_bytes()) == joint_sha, "STALE_WORLD_DECISION")
    return dict(release=pin, identity=plan["identity"], instance=plan["instance"], birth_sha256=birth_sha,
                decision_joint_sha256=joint_sha, **route)


def feedback_payload(plan, gate, response):
    raw = response["display"]["text"].encode("utf8")
    need(response["identity"] == plan["identity"] and response["instance"] == plan["instance"]
         and response["folder_request_sha256"] == gate["folder_request"]
         and response["status"] == "VERIFIED" and response["readback_only"] is False
         and sha(raw) == plan["items"][0]["content_sha256"], "FEEDBACK_RECEIPT")
    value = parse(raw)
    fields(value, "object_id outcome")
    need(value["object_id"] == gate["selected"] and value["outcome"] in ("cooperate","decline","harm"),
         "FIXTURE_FEEDBACK_DOMAIN")
    # The native control stores a 32-hex interaction ID. Link it to this exact closed response.
    return dict(sandbox=True, interaction_id="sandbox_" + digest([gate,response])[:32], **value)


def practice(plan, pin, pins):
    import base
    from observe import Trace
    from offline import transaction
    from common import json_file, put
    base.enable_numeric(pins)
    from al01.integrated import IntegratedLife
    put(BIRTH, LIVE.read_bytes())
    life = IntegratedLife(LIVE.parent)
    need(life.individual.state["id"] == plan["identity"] and life.generation == 0, "FRESH_TEST_REQUIRED")
    session = dict(identity=plan["identity"], run_id=plan["run_id"], freeze_sha256=pin)
    for i in (1,2):
        with Trace() as trace:
            record = transaction(life, RUN, session, "amber", i)
        need(record["binding"]["instance"] == plan["instance"] and
             trace.counts["al01.core.World.observe"] == 1 and not trace.blocked, "WORLD_EXECUTION")
        json_file("run/world-transaction-%d.json" % i, dict(record=record, trace=trace.data()))
    put(DECISION, LIVE.read_bytes())
    return decision(plan, pin, live=True)


def apply_receipt(plan, pin, wire):
    import bridge
    from al01.integrated import IntegratedLife
    from common import json_file
    gate = decision(plan, pin, live=True)
    response = bridge.settled(plan, wire, pin)
    payload = feedback_payload(plan, gate, response)
    life = IntegratedLife(LIVE.parent)
    need(not life.modules["social_ledger"]["events"] and not life.modules["control_audit"], "ALREADY_APPLIED")
    life._control("sandbox_interaction", payload)
    event, = life.modules["social_ledger"]["events"]
    need(event["payload"] == payload and life.generation == 5 and life.individual.state["tick"] == 4,
         "FEEDBACK_NOT_SAVED")
    json_file("run/feedback.json", dict(identity=plan["identity"], release=pin, receipt=response["receipt_ref"],
              receipt_sha256=digest(response), gate_sha256=digest(gate), event=event,
              world_joint_sha256=sha(LIVE.read_bytes())))


def cold_world(plan, pin, response):
    from al01.integrated import IntegratedLife
    from offline import settled_receipt
    from al01.development import relationship_value
    import copy
    import re
    checkpoints = [frame(path)[0] for path in (BIRTH, DECISION, LIVE)]
    for wrap in checkpoints:
        individual, _, _ = IntegratedLife._decode(wrap["data"])
        need(individual.state["id"] == plan["identity"], "COLD_IDENTITY")
    _, decision_frame, final = checkpoints
    before, after = decision_frame["data"], final["data"]
    gate = decision(plan, pin)
    journal = frame(LIVE.with_name("actions.json"))[0]["data"]["records"]
    events = before["core_joint"]["individual"]["state"]["events"]
    need(len(journal) == 2, "WORLD_JOURNAL_COUNT")
    for i, target in enumerate(("object_0000", plan["route_target"]), 1):
        commit, feedback = events[2*i-2:2*i]
        req = commit["payload"]["action_requested"]
        oid = req["action_id"]
        settled_receipt(req, journal[oid], feedback)
        tx = parse((RUN / ("world-transaction-%d.json" % i)).read_bytes())
        record = tx["record"]
        path = RUN / ("m5-%d.sqlite" % i)
        route = dict(original_id=oid, job="world-%d" % i, campaign=plan["instance"])
        bound = dict(identity=plan["identity"], instance=plan["instance"], freeze_sha256=pin,
                     origin="R13_SIMULATED_WORLD", request=req, commit_head=commit["hash"])
        h = digest(bound)
        with closing(sqlite3.connect(path.as_uri()+"?mode=ro", uri=True)) as db:
            need(db.execute("SELECT * FROM action").fetchall() == [(oid,h,"COMPLETED",None)]
                 and db.execute("SELECT * FROM authority").fetchall() == [(plan["instance"],)]
                 and db.execute("SELECT * FROM binding").fetchall() == [(route["job"],plan["instance"],oid)],
                 "WORLD_ORIGINAL_M5")
        rows = record["rows"]
        need(record["route"] == route and record["binding"] == bound and record["db_sha256"] == sha(path.read_bytes())
             and record["receipt"] == journal[oid] and record["feedback"] == feedback
             and feedback["payload"]["target"] == target and tx["trace"]["calls"]["al01.core.World.observe"] == 1
             and [row["state"] for row in rows] == ["PLANNED","RESERVED","COMPLETED"]
             and all(row["request_sha256"] == h for row in rows)
             and re.fullmatch("[0-9a-f]{64}", rows[1]["claim_sha256"]), "WORLD_TX_BINDING")
    payload = feedback_payload(plan, gate, response)
    incoming = after["modules"]
    event, = incoming["social_ledger"]["events"]
    target = payload["object_id"]
    relation = incoming["development"]["content"]["relationships"][target]
    refs = relation["source_refs"]
    need(after["parent_bundle"] == decision_frame["sha256"] and after["generation"] == 5
         and after["core_joint"]["individual"] == before["core_joint"]["individual"]
         and not before["modules"]["social_ledger"]["events"] and event["payload"] == payload
         and event["hash"] == digest({k:v for k,v in event.items() if k!="hash"})
         and event["kind"] == "sandbox_interaction" and relation["count"] == 1
         and len(refs) == 1 and refs[0]["hash"] == event["hash"]
         and refs[0] in incoming["development"]["processed"]
         and incoming["control_audit"][0]["payload"] == payload, "COLD_RECEIPT_FEEDBACK")
    prior = relationship_value(before["modules"]["development"], target)
    need(prior == 0.5 and relation["K"] == 0.9*prior + 0.1*{"cooperate":1,"decline":0.5,"harm":0}[payload["outcome"]],
         "COLD_RELATION_DELTA")
    log = parse((RUN/"feedback.json").read_bytes())
    need(log == dict(identity=plan["identity"], release=pin, receipt=response["receipt_ref"],
         receipt_sha256=digest(response), gate_sha256=digest(gate), event=event,
         world_joint_sha256=sha(LIVE.read_bytes())), "FEEDBACK_LOG")
    altered = copy.deepcopy(before)
    altered["modules"]["governance"][1]["arbitration"]["action_id"] = "object_0002"
    try:
        select(altered, plan)
    except ValueError as exc:
        need(str(exc) == "NO_MATCHING_WORLD_POLICY", "CONTROL_REASON")
    else:
        raise AssertionError("changed arbitration accepted")
    return dict(core_tick=4, generation=5, phase=after["core_joint"]["phase"], world_actions=2,
                approved=target, first_observation=events[1]["payload"], interaction=payload,
                source_event=event["hash"], relationship_before=prior, relationship_after=relation["K"],
                wrong_policy="NO_MATCHING_WORLD_POLICY", gate=gate)

