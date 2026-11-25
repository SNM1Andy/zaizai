"""Real host/ledger swap drill with a temporary contract provider and a detached copy of the actual save."""
import argparse
import base64
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from check_slots31 import FIXTURE

def need(ok,note):
    if not ok:raise AssertionError(note)
def sha(data):return hashlib.sha256(data).hexdigest()
def packed(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"))
def child(r,rid):
    sys.path.insert(0,str(r/"host"));import service as s
    def cut(phase):
        if phase=="slot":os._exit(86)
    s.process("读回我刚交给测试槽的观察号","swap_check",rid,source="acceptance",checkpoint=cut)
    raise AssertionError("did not reach real C8 boundary")
def main(inst,archive,overlay=False):
    import zipfile
    with tempfile.TemporaryDirectory(prefix="zaizai-host-slot-swap-") as t:
        root=Path(t).resolve()
        shutil.copytree(inst/"host",root/"host",ignore=shutil.ignore_patterns("__pycache__","*.pyc"))
        if overlay:
            source=Path(__file__).resolve().parents[1]/"host"
            for f in ("slots31.py","slot31_transport.py","slot31_legacy.py"):shutil.copyfile(source/f,root/"host"/f)
        shutil.copytree(inst/"lexicon",root/"lexicon");(root/"bin").mkdir()
        for f in ("cl.exe","pcgm-alpha.exe","pcgm-beta.exe"):shutil.copy2(inst/"bin"/f,root/"bin"/f)
        (root/"evidence").mkdir()
        for f in ("legacy-reopen.json",):
            if (inst/"evidence"/f).exists():shutil.copyfile(inst/"evidence"/f,root/"evidence"/f)
        with zipfile.ZipFile(archive) as z:
            manifest=json.loads(z.read("manifest.json"))
            for rel,pin in manifest["files"].items():
                dest=(root/"state"/rel).resolve();need(dest.is_relative_to(root/"state") and not dest.exists(),rel)
                dest.parent.mkdir(exist_ok=True,parents=True)
                data=z.read("state/"+rel);need(sha(data)==pin,rel);dest.write_bytes(data)
        os.environ["PYTHONDONTWRITEBYTECODE"]="1"
        sys.path.insert(0,str(root/"host"));import service as s,native as n,slots31 as api
        need(n.ROOT==api.ROOT==root,"working installation mismatch")
        def rows(sql,values=()):
            with closing(s.store()) as db:return [tuple(x) for x in db.execute(sql,values)]
        def binding(L=None,C=None):
            with s.writer(),closing(s.store()) as d,d:return api.bind(d,language=L,cognition=C)
        def turn(q,rid):return s.process(q,"swap_check",rid,source="acceptance")
        s.setup()
        prior=rows("select seq,identity,request,response,build from turns order by seq")
        old_receipts=rows("select id,session,digest,phase,plan,native_receipt from requests order by id")
        old_memory=rows("select * from memory order by name")
        original_identity=n.IDENTITY;session="swap_check";notes={}
        binding("legacy-cl","legacy-pcgm")
        legacy_q="证明 identity_restored(zaizai)";legacy=turn(legacy_q,"swapoldproof")
        native_hash=sha(n.SAVE.read_bytes());need(json.loads(legacy["plan"]).get("proof"),legacy["answer"])
        # Synthetic providers are only present in this temporary catalogue, never in the install under test.
        with s.writer(),closing(s.store()) as db,db:
            for role in ("L","C"):
                aid="fixture-"+role.lower();folder=root/"slot-providers"/aid;folder.mkdir(parents=True)
                script=folder/"provider.py";script.write_text(FIXTURE,encoding="utf8");entry=script.relative_to(root).as_posix()
                m={"slot":role,"id":aid,"name":"仅换件验收用的受控件","version":"fixture-only/1","interface_version":api.ABI,
                   "provider_type":"external","entry":entry,"artifacts":{entry:sha(script.read_bytes())},
                   "formats":[],"state_format":"fixture-sql-as-json/1","capabilities":list(api.PORTS[role]),
                   "value_domain":{"support":"attested","counter":"refuted","insufficient":"open"} if role=="L" else {}}
                (folder/"manifest.json").write_text(api.canonical(m),encoding="utf8")
                db.execute("INSERT INTO slot31_registry VALUES(?,?,?,?)",(aid,role,api.canonical(m),api.hash_json(m)))
        binding("empty","empty");empty=turn("普通问题等待合格件","swapempty");need(json.loads(empty["plan"])["frame_kind"]=="slot_status","empty host invented reply")
        remembered=turn("回忆 object_0000","swapreadmemory");need("object_0000" in remembered["answer"],"empty host lost historical memory")
        binding("fixture-l","empty")
        partial=turn("普通问题等待认知槽","swaphalf")
        need(json.loads(partial["plan"])["frame_kind"]=="slot_status","partial slot invented reply")
        binding("fixture-l","fixture-c")
        wait=turn("暂时没有已确认结论","swapwait")
        wait_plan=json.loads(wait["plan"]);need(wait_plan["frame_kind"]!="reply" and wait["native_receipt"] is None,"shelved work produced a cognitive reply")
        req="swapfixture";q="读回我刚交给测试槽的观察号"
        reply=turn(q,req);plan=json.loads(reply["plan"])
        need(plan["frame_kind"]=="reply" and req in reply["answer"],"fixture reply did not read its actual observed id")
        ports=[f["port"] for f in plan["port_receipts"]]
        need(ports==["L1","C1","C5","L4"] and json.loads(reply["native_receipt"])["request"]==req,ports)
        need(turn(q,req)["seq"]==reply["seq"],"duplicate host turn")
        crashid="swapmidcommit"
        c=subprocess.run([sys.executable,"-X","utf8","-B",__file__,"--child",root,"--rid",crashid],
                         capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
        need(c.returncode==86,(c.returncode,c.stderr.decode("utf8","replace")[-300:]))
        need(rows("select phase from requests where id=?",(crashid,))==[("prepared",)],"wrong crash phase")
        need(not rows("select request_id from host31_commits where request_id=?",(crashid,)),"host commit already published")
        try:binding(C="legacy-pcgm")
        except ValueError as exc:need("对账" in str(exc),"wrong denial")
        else:raise AssertionError("in-flight C8 moved to another provider")
        undone=turn(q,crashid);need(undone["phase"]=="committed","failed to reconcile original C8")
        fx=root/"slot-providers/fixture-c/fixture-state.sqlite"
        with closing(sqlite3.connect(fx)) as store:
            need(store.execute("select count(*) from log where k=?",(crashid,)).fetchone()[0]==1,"duplicate fixture effect")
        with s.writer(),closing(s.store()) as d,d:
            captured=api.capture_private(d)
            payload=d.execute("select opaque from slot31_private_state where adapter_id='fixture-c'").fetchone()[0]
            need(sha(payload)==captured["state_sha256"] and any(x[0]==crashid for x in json.loads(payload)["log"]),"C9 omitted prior C8 effect")
        binding(C="empty")
        # Remove only this test double's private state to force a physical restore from host-owned bytes.
        os.rename(fx,fx.with_name("detached-first-copy.sqlite"))
        need(not fx.exists(),"unexpected live fixture file")
        binding(C="fixture-c")
        with closing(sqlite3.connect(fx)) as reopened:
            restored=reopened.execute("select k,value from log order by k").fetchall()
        need(restored==[tuple(x) for x in json.loads(payload)["log"]],"provider process failed to rehydrate private C8 effects")
        # Simulate coordinated archive restoration across two processes. A pending C9 may not be overwritten.
        with s.writer(),closing(s.store()) as d,d:
            m=api.checkpoint(d)["C"]
            d.execute("insert into slot31_private_restore_due values(?,?,?)",(m["id"],m["manifest_sha256"],captured["state_sha256"]))
        os.rename(fx,fx.with_name("detached-second-copy.sqlite"))
        with s.writer(),closing(s.store()) as d,d:
            preserved=api.capture_private(d);need(preserved["storage"]=="pending_restore" and not fx.exists(),"pending C9 was overwritten")
            api.dispatch(d,"C5",{"preempt":True,"has_work":True,"budget_ms":90})
            need(not d.execute("select 1 from slot31_private_restore_due").fetchone(),"first use did not resume pending C9")
        with closing(sqlite3.connect(fx)) as reopened:need(reopened.execute("select k,value from log order by k").fetchall()==restored,"delayed restore lost effects")
        binding("legacy-cl","legacy-pcgm")
        need(sha(n.SAVE.read_bytes())==native_hash,"new provider wrote into old PCGM save")
        replay=turn(legacy_q,"swapoldproof");need(replay["seq"]==legacy["seq"] and replay["native_receipt"]==legacy["native_receipt"],"old receipt changed")
        final=turn(legacy_q,"swapoldagain");need(json.loads(final["plan"])["proof"]["proof"]["results"][0]["status"]=="POSITIVE","restored legacy proof invalid")
        need(rows("select seq,identity,request,response,build from turns order by seq limit ?",(len(prior),))==prior,"input history changed")
        need(rows("select * from memory order by name")==old_memory,"persistent host memory changed")
        for rid,session,digest,phase,plan,raw in old_receipts:
            need(rows("select session,digest,phase,plan,native_receipt from requests where id=?",(rid,))==[(session,digest,phase,plan,raw)],"earlier request changed")
        need(n.IDENTITY==original_identity and all(v[0]==original_identity for v in rows("select distinct identity from turns")),"identity changed")
        if_dir=rows("select frame_kind from host31_commits where request_id=?",(crashid,))
        return {"passed":True,"test_provider_only":True,"source_archive_sha256":sha(archive.read_bytes()),"identity":n.IDENTITY,
            "checked_old_turns":len(prior),"checked_old_requests":len(old_receipts),"memory_entries_preserved":len(old_memory),
            "route_sequence":["legacy/legacy","empty/empty","fixture/empty","fixture/fixture","fixture/empty","fixture/fixture","legacy/legacy"],
            "legacy_receipt_same":True,"bound_commit_kind":if_dir[0][0],"crash_after_provider_commit":True,"inflight_change_rejected":True,
            "one_private_effect":True,"raw_c8_effects_after_restore":len(restored),"c9_size":captured["bytes"],"c9_sha256":captured["state_sha256"],
            "slot_state_physically_recreated":True,"pending_restore_on_first_use":True,
            "empty_frame":json.loads(empty["plan"])["frame_kind"],"no_conclusion_frame":wait_plan["frame_kind"],
            "fixture_reply_ports":[*ports,"C8"],"reply_quote":reply["answer"],"new_provider_activated_in_live":False,
            "host_source_sha256":{f:sha((root/"host"/f).read_bytes()) for f in ("service.py","host_turn31.py","slots31.py","slot31_legacy.py","slot31_transport.py")}}
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--root",type=Path);p.add_argument("--archive",type=Path);p.add_argument("--out",type=Path)
    p.add_argument("--development-overlay",action="store_true");p.add_argument("--child",type=Path);p.add_argument("--rid")
    args=p.parse_args()
    if args.child:child(args.child.resolve(strict=True),args.rid)
    else:
        result=main(args.root.resolve(strict=True),args.archive.resolve(strict=True),args.development_overlay)
        if args.out:args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf8")
        print("PASS host swap, pinned in-flight request, original receipt, C9 physical recovery",result["c9_size"])

