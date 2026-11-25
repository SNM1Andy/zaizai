"""Exercise all L/C ABI ports and process failures on copies. Fixtures are never registered in the live host."""
import argparse
from contextlib import closing,ExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile

FIXTURE=r'''
import base64, hashlib, json, pathlib, sqlite3, sys, time
f=json.loads(sys.stdin.buffer.readline());p=f["input"];k=f["port"];m=json.loads(pathlib.Path(__file__).with_name("manifest.json").read_bytes())
def pin(x):return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
def database():
    db=sqlite3.connect(pathlib.Path(__file__).with_name("fixture-state.sqlite"))
    db.execute("create table if not exists log(k primary key, value)")
    db.execute("create table if not exists observations(k primary key, value)")
    return db
def state_bytes(db):
    return json.dumps({table:list(db.execute("select k,value from "+table+" order by k")) for table in ("log","observations")},
                      ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
if p.get("inject")=="timeout":time.sleep(2)
if p.get("inject")=="crash":sys.exit(19)
if p.get("inject")=="invalid":sys.stdout.write("bad output");sys.exit()
src=["test-fixture:"+m["id"]]
if k=="L1":o={"parsed":{"term":p["text"]}}
elif k=="L2":o={"results":[{"goal":{"predicate":"example","arguments":[]},"status":"attested"}],"proof_ref":pin(p)}
elif k=="L3":o={"meanings":[["test","fixture"]],"ambiguous":False,"proposals":[]}
elif k=="L4":o={"text":p["conclusion"]["text"]};src=p["conclusion"]["evidence_refs"]
elif k=="L5":o={"matches":True,"proof_ref":p["receipt"]["output"]["proof_ref"]}
elif k=="L6":o={"passed":True,"capabilities":m["capabilities"]}
elif k=="C1":
    with database() as db:
        val=json.dumps(p,ensure_ascii=False,sort_keys=True);old=db.execute("select value from observations where k=?",(p["id"],)).fetchone()
        if old and old[0]!=val:sys.exit(3)
        db.execute("insert or ignore into observations values(?,?)",(p["id"],val))
    o={"accepted":True,"id":p["id"]}
elif k=="C2":o=dict(p)
elif k=="C3":o={"candidates":[]}
elif k=="C4":o={"questions":[]}
elif k=="C5":
    o={"mode":"wait" if p.get("preempt") else "ready","budget_ms":p.get("budget_ms",1),"wake":"host-event"}
    if not p.get("preempt") and p.get("observation_id"):
        with database() as db:found=db.execute("select value from observations where k=?",(p["observation_id"],)).fetchone()
        if found and json.loads(found[0]).get("content")=="读回我刚交给测试槽的观察号":
            basis="fixture-observation:"+pin(json.loads(found[0]))
            o["conclusion"]={"text":"这个独立测试槽收到的观察号为 "+p["observation_id"]+"。","evidence_refs":[basis]}
            src=[basis]
elif k=="C6":o=dict.fromkeys(("integrity","unresolved_weight","prediction_error","information_gain"))
elif k=="C7":o={"round_id":p["round_id"],"entries":[]}
elif k=="C8":
    ph="prepared"
    if p["phase"]=="commit":
        with database() as db:
            val=pin([p["session"],p["action"]]);old=db.execute("select value from log where k=?",(p["request"],)).fetchone()
            if old and old[0]!=val:sys.exit(2)
            db.execute("insert or ignore into log values(?,?)",(p["request"],val));ph="replayed" if old else "committed"
    o={"phase":ph,"request":p["request"],"receipt":"fixture:"+p["request"]}
else:
    with database() as db:
        if p["operation"]=="restore":
            blob=base64.b64decode(p["opaque_base64"],validate=True)
            if hashlib.sha256(blob).hexdigest()!=p["state_sha256"] or p["state_format"]!=m["state_format"]:sys.exit(4)
            state=json.loads(blob)
            for table in ("log","observations"):
                db.execute("delete from "+table)
                db.executemany("insert into "+table+" values(?,?)",state[table])
        blob=state_bytes(db)
        o={"operation":p["operation"],"state_format":m["state_format"],"state_sha256":hashlib.sha256(blob).hexdigest()}
        if p["operation"]=="save":o["opaque_base64"]=base64.b64encode(blob).decode()
answer={k:f[k] for k in ("interface_version","slot","port","adapter","version","input_version")}
answer.update(sources=src,output=o)
if p.get("inject")=="wrong_version":answer["input_version"]="other"
if p.get("inject")=="out_of_domain":answer["output"]["results"][0]["status"]="other"
sys.stdout.write(json.dumps(answer,ensure_ascii=False))
'''
def need(condition,detail):
    if not condition:raise AssertionError(detail)
def run(inst,archive):
    here=Path(__file__).resolve().parents[1]/"host"
    src=inst/"host"
    with tempfile.TemporaryDirectory(prefix="zaizai-slots31-contract-") as working,ExitStack() as handles:
        test=Path(working).resolve()
        for d in ("host","bin","lexicon","state","slot-providers"): (test/d).mkdir()
        for name in ("slots31.py","slot31_legacy.py","slot31_transport.py","legacy_memory.py","native.py","host_memory31.py"):
            original=(here/name) if (here/name).is_file() else src/name
            shutil.copy2(original,test/"host"/name)
        shutil.copytree(inst/"lexicon",test/"lexicon",dirs_exist_ok=True)
        for name in ("cl.exe","pcgm-alpha.exe","pcgm-beta.exe"):shutil.copy2(inst/"bin"/name,test/"bin"/name)
        with zipfile.ZipFile(archive) as z:
            for full in z.namelist():
                if full in ("state/individual.pcgm","state/native/joint-reopen.json") or full.startswith(("state/individual.pcgm.history/","state/individual.pcgm.episodes/","state/modules/")):
                    if full.endswith("/"):continue
                    dest=(test/full).resolve();need(dest.is_relative_to(test/"state"),"archive path escaped")
                    dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(z.read(full))
        sys.path.insert(0,str(test/"host"))
        import slots31 as a
        import slot31_legacy as old
        import host_memory31 as mem
        need(a.ROOT==test,"wrong root")
        dbfile=test/"state/contract.sqlite";d=handles.enter_context(closing(sqlite3.connect(dbfile)));d.row_factory=sqlite3.Row
        with d:a.setup(d);mem.setup(d)
        original=hashlib.sha256((test/"state/individual.pcgm").read_bytes()).hexdigest()
        report={}
        with d:
            need(all(v["state"]=="empty" for v in a.snapshot(d).values()),"default bindings")
            for port in ("L2","C8"):
                try:a.dispatch(d,port,{})
                except a.SlotUnavailable as err:need(err.code=="empty","empty slot code")
                else:raise AssertionError("empty slot produced output")
        with d:
            p=a.bind(d,language="legacy-cl");need(p["C"]["state"]=="empty" and p["L"]["state"]=="ready","independent binding")
            a.bind(d,cognition="legacy-pcgm")
        def call(port,params,**opts):
            with d:
                f=a.dispatch(d,port,params,**opts);need(f["input_version"] and f["sources"] and f["port"]==port,"unattributed output");return f
        source=old.CHECK_SOURCE;text="known(x)"
        inputs={
            "L1":{"text":text,"context":{}},"L2":{"source":source},"L3":{"word":"验证"},
            "L4":{"conclusion":{"text":"已记录本次证据。","evidence_refs":["receipt:one"]}},"L6":{},
            "C1":{"id":"obs-one","source":"test:input","channel":"local","speaker":"test","at":1.,"content":"known"},
            "C2":{"operation":"read","filter":{"limit":5}},"C3":{"offers":[{"id":"study","cost":1}],"evidence_by_lane":{"study":{"ref":"test:L2"}}},
            "C4":{},"C5":{"budget_ms":30,"preempt":True,"has_work":True},"C6":{},"C7":{"round_id":"contractturn"},
            "C8":{"phase":"prepare","request":"contractturn","session":"contract","action":"record h"+"3"*64},"C9":{"operation":"describe"}}
        results={}
        for port,pay in inputs.items():results[port]=call(port,pay)
        out=results["L2"]["output"];inputs["L5"]={"source":source,"receipt":results["L2"]}
        results["L5"]=call("L5",inputs["L5"])
        need(results["L5"]["output"]["matches"],"L5 replay")
        need([r["status"] for r in out["results"]]==["POSITIVE","NEGATIVE","UNKNOWN"],"distinct status semantics")
        need(results["L3"]["output"]["ambiguous"],"lexicon ambiguity")
        need(results["C3"]["output"]["candidates"][0]["base_score"]==.72,"legacy bounded offer mapping")
        need(results["C5"]["output"]["mode"]=="wait","foreground preemption")
        need(results["C6"]["output"]["prediction_error"] is None,"fabricated measurement")
        need(call("C1",inputs["C1"])==results["C1"],"C1 replay")
        with d:mem.observe(d,"obsA","dialogue","同一事实","local:test","用户",{"session":"main"})
        p={"operation":"append","record":{"id":"derived:sample","kind":"semantic","body":"候选说明","derived":["obsA"],"confidence":"hypothesis"}}
        ack=call("C2",p)["output"]
        need(not ack.get("refused"),("C2 valid derivation",ack))
        forbidden=call("C2",{"operation":"append","record":{"id":"derived:self","kind":"semantic","body":"self","derived":["derived:self"],"confidence":"hypothesis"}})["output"]
        need(forbidden.get("refused"),"self-proof accepted")
        before=old.status(test,time.monotonic()+3)["state"]["event"];c8=dict(inputs["C8"],phase="commit")
        first=call("C8",c8);second=call("C8",c8)
        after=old.status(test,time.monotonic()+3)["state"]["event"]
        need(first==second and before+1==after and first["output"]["request"]=="contractturn","C8 duplicated native effect")
        replay=call("C7",inputs["C7"]);need(replay["output"]["entries"],"C7 no actual receipt")
        saved=call("C9",{"operation":"save"})["output"]
        result=call("C9",dict(saved,operation="restore"))["output"];need(result["reopened"],"state reopen")
        need(call("L1",{"text":""})["output"].get("refused"),"invalid expression not explicitly refused")
        need(call("L2",{"source":"? invalid(\n"})["output"].get("refused") and a.snapshot(d)["L"]["state"]=="ready","invalid source disabled healthy language provider")
        r=call("L2",{"operation":"offer_eligibility","offers":[{"id":"study","available":True},{"id":"flow","available":False}]})["output"]["results"]
        need({x["subject"]:x["status"] for x in r}=={"study":"POSITIVE","flow":"NEGATIVE"},"offer provenance")
        report["legacy_ports"]={k:{"passed":True,"sources":v["sources"][:2]} for k,v in sorted(results.items())}
        report["legacy_c8_native_events_added"]=after-before
        report["real_l2_statuses"]=[r["status"] for r in out["results"]]
        report["c2_invalid_derived_blocked"]=True
        report["legacy_state_reopened"]=True
        post=hashlib.sha256((test/"state/individual.pcgm").read_bytes()).hexdigest()
        with d:a.bind(d,language="empty",cognition="empty")
        fixtures={}
        for role in ("L","C"):
            aid="fixture-"+role.lower();base=test/"slot-providers"/aid;base.mkdir()
            (base/"provider.py").write_text(FIXTURE,encoding="utf8")
            rel=(base/"provider.py").relative_to(test).as_posix()
            m={"id":aid,"slot":role,"name":"契约测试替身","version":"fixture-only/1","interface_version":a.ABI,
               "capabilities":list(a.PORTS[role]),"value_domain":{"support":"attested","counter":"refuted","insufficient":"open"} if role=="L" else {},
               "formats":[],"state_format":"fixture-json/1","provider_type":"external","entry":rel,
               "artifacts":{rel:hashlib.sha256((base/"provider.py").read_bytes()).hexdigest()}}
            (base/"manifest.json").write_text(a.canonical(m),encoding="utf8");fixtures[role]=m
            try:a.register_release(d,aid)
            except ValueError as exc:need("凭据" in str(exc),"wrong denial for missing independent certificate")
            else:raise AssertionError("uncertified provider was admitted")
            # This is only a separate test catalogue. A real installer must go through register_release.
            with d:d.execute("INSERT INTO slot31_registry VALUES(?,?,?,?)",(aid,role,a.canonical(m),a.hash_json(m)))
        with d:a.bind(d,language="fixture-l",cognition="fixture-c")
        external={}
        for port,pay in inputs.items():
            if port=="L5":
                try:call("L5",inputs["L5"])
                except a.SlotUnavailable as exc:need(exc.code=="binding_changed","cross-adapter old proof replay")
                else:raise AssertionError("incoming provider reinterpreted the outgoing provider's proof")
                pay={"source":source,"receipt":call("L2",inputs["L2"])}
            v=call(port,pay)
            need(v["adapter"]=="fixture-"+port[0].lower(),"unexpected adapter selection")
            external[port]=True
        need(call("L2",inputs["L2"])["output"]["results"][0]["status"]=="attested","host fixed to old L2 domain")
        f8=call("C8",c8)
        with d:d.execute("DELETE FROM slot31_port_receipts WHERE adapter='fixture-c' AND port='C8' AND event_id='contractturn'")
        f8b=call("C8",c8);need(f8b["output"]["phase"]=="replayed","provider did not recover unacknowledged effect")
        failures={}
        for kind,expected in [("timeout","timeout"),("crash","crash"),("invalid","invalid"),("wrong_version","invalid"),("out_of_domain","invalid")]:
            with d:
                try:a.dispatch(d,"L2",{"source":"ok","inject":kind},timeout_ms=80 if kind=="timeout" else 1000)
                except a.SlotUnavailable as exc:need(exc.code==expected,(kind,exc.code,str(exc)));failures[kind]=exc.code
                else:raise AssertionError("invalid response accepted: "+kind)
            need(a.snapshot(d)["L"]["state"]=="unavailable" and a.snapshot(d)["C"]["state"]=="ready","failure escaped slot boundary")
            with d:a.bind(d,language="fixture-l")
        with d:a.bind(d,language="legacy-cl",cognition="legacy-pcgm")
        need(hashlib.sha256((test/"state/individual.pcgm").read_bytes()).hexdigest()==post,"switch changed native state")
        need(call("L5",inputs["L5"])["output"]["matches"],"old proof was reinterpreted after provider switch")
        d.close()
        with closing(sqlite3.connect(dbfile)) as reopened:
            check=a.checkpoint(reopened);need(check["L"]["id"]=="legacy-cl" and check["C"]["id"]=="legacy-pcgm","binding not restorable")
        report.update(external_fixture_ports=external,isolated_failures=failures,swap=["legacy","empty","contract-fixture","legacy"],
                      original_private_sha256=original,post_commit_private_sha256=post,empty_does_not_execute=True,
                      unaudited_provider_denied=True,previous_proof_reproduced=True,persisted_binding=True,real_replacement_available=False)
        return report
if __name__=="__main__":
    arg=argparse.ArgumentParser();arg.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1])
    arg.add_argument("--archive",type=Path,required=True);arg.add_argument("--out",type=Path);opts=arg.parse_args()
    result=run(opts.root.resolve(strict=True),opts.archive.resolve(strict=True))
    if opts.out:opts.out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf8")
    print("PASS legacy ports",len(result["legacy_ports"]),"fixture ports",len(result["external_fixture_ports"]),result["isolated_failures"])

