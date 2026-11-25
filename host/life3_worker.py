"""Windows user-mode worker and supervisor for the same installed individual."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
from uuid import uuid4

import native as n
import service
import life3 as life
import study3
import inner3
import evolution3
import inquiry3
import round31
import slots31
import life_slots31 as boundary
from gpu_readout import Readout

ROOT=n.ROOT
K=ctypes.WinDLL("kernel32",use_last_error=True)
K.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p]
K.CreateMutexW.restype=ctypes.c_void_p
K.OpenMutexW.argtypes=[ctypes.c_uint,ctypes.c_bool,ctypes.c_wchar_p]
K.OpenMutexW.restype=ctypes.c_void_p
K.CloseHandle.argtypes=[ctypes.c_void_p]
TAG="Local\\Zaizai3-"+hashlib.sha256(str(ROOT).casefold().encode()).hexdigest()[:16]+"-"
@contextmanager
def latch(name,exclusive=False):
    h=K.CreateMutexW(None,False,TAG+name)
    existed=ctypes.get_last_error()==183
    if not h:raise ctypes.WinError(ctypes.get_last_error())
    try:yield not (exclusive and existed)
    finally:K.CloseHandle(h)
def active(name):
    h=K.OpenMutexW(0x100000,False,TAG+name)
    if not h:return False
    K.CloseHandle(h);return True
def spawn(script,*args):
    return subprocess.Popen([str(n.PYTHON),"-B","-X","utf8",str(script),*map(str,args)],cwd=ROOT,
                            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW)
def start():
    if not active("supervisor"):
        spawn(Path(__file__),"supervise")
def lifecycle_log(name,detail):
    folder=ROOT/"evidence/life3";folder.mkdir(parents=True,exist_ok=True)
    with (folder/"runtime.jsonl").open("a",encoding="utf8") as f:
        f.write(json.dumps({"time":time.time(),"kind":name,"detail":str(detail)[:1500]},ensure_ascii=False)+"\n")

def select_step(db,resources=None):
    if active("foreground"):return None
    deadline=[time.monotonic()+boundary.WORK_MS/1000]
    def remaining():return boundary.remaining(deadline[0],lambda:active("foreground"))
    with slots31.quota_context(remaining):
        return _select_step(db,resources,deadline,remaining)

def _select_step(db,resources,deadline,remaining):
    identifier="life-"+uuid4().hex
    db.execute("BEGIN IMMEDIATE")
    b=None
    try:
        if life.meta(db,"paused")=="1" or life.meta(db,"enabled")!="1":
            db.rollback();return None
        remaining()
        b=boundary.bindings(db)
        indexed=boundary.index_materials(db)
        ack=boundary.deliver_frame(db,b,remaining())
        binds_key=boundary.pin(b)
        # M8 consumes only recorded failures, actual assignments and the independent release gate.
        # New or empty slots have no authority over its policy, or over whether prior evidence is processed.
        maintenance=evolution3.advance(db)
        if not boundary.pair_available(b):
            reason=boundary.wait_reason(db,"宿主待命 · 槽未就绪",binds_key)
            if life.meta(db,"mode")!=reason:life.put(db,"mode",reason)
            if maintenance:
                event=dict(maintenance,receipt=identifier,executed_lane="maintenance",duration_ms=max(0,(boundary.WORK_MS-remaining())))
                life.audit(db,identifier,event)
            elif indexed:
                event={"kind":"host_index","topic":"观察帧","summary":f"登记 {indexed} 个带来源和版本的材料帧，学习阶段保持原值。",
                       "source":"local:host-observation-queue","status":"waiting","executed":False,
                       "progress":False,"frame_kind":"host_data","host_status":True,"receipt":identifier}
                life.audit(db,identifier,event)
            else:event=None
            remaining();db.commit();return event
        native_available=boundary.supports(b["C"],"C4") and life.meta(db,"feed_seen")!=life.question_feed_revision(db,b)
        previous=life.meta(db,"last_lane")
        backlog=db.execute("SELECT COUNT(*) FROM life3_events WHERE integrated=0").fetchone()[0]
        due_flows=db.execute("SELECT COUNT(*) FROM life3_flows WHERE examined=0").fetchone()[0]
        ago=time.time()-float(life.meta(db,"last_integration","0"))
        pressure=bool(resources and (resources["temp_c"]>=87 or resources["free_mib"]<3072))
        pending=study3.pending(db)
        # Host tasks that require the old authored CL curriculum keep that format bound to its adapter.
        compatible_language=".cl" in (b["L"].get("formats") or ())
        offers={
            "study":{"available":bool(pending and compatible_language),"demand_count":pending},
            "flow":{"available":bool(due_flows and compatible_language),"demand_count":due_flows},
            "integration":{"available":bool(backlog and (backlog>=5 or ago>70 or pressure)),"demand_count":backlog},
            "native":{"available":native_available,"demand_count":int(native_available)}}
        for name,offer in offers.items():
            permission,cost=boundary.LANES[name]
            offer.update(id=name,permission=permission,cost=cost)
        has_work=any(x["available"] for x in offers.values())
        latest_input=db.execute("""SELECT id FROM life31_frames WHERE category!='host_event'
                                   ORDER BY rowid DESC LIMIT 1""").fetchone()
        wake_key=boundary.pin([binds_key,offers,pressure,latest_input[0] if latest_input else None,
                               evolution3.policy(db)["revision"]])
        # Maintenance is transactional host policy work; it never creates a cognitive response.
        event=maintenance
        decision=None;lane="maintenance"
        if not event and has_work:
            if life.meta(db,"slot31_wait_input")==wake_key and time.time()<float(life.meta(db,"slot31_wait_until","0")):
                db.commit();return None
            units=2 if pressure else boundary.WORK_UNITS
            inputs={"round_id":identifier,"previous_lane":previous,"offers":list(offers.values()),"resource_pressure":pressure,
                    "resources":resources,"budget_units":units,"backlog":backlog,"pending_study":pending,"unchecked_flows":due_flows}
            now_quota=remaining()
            plan=boundary.port_call(db,"C5",{"budget_ms":now_quota,"preempt":False,"has_work":True},budget_ms=now_quota)["output"]
            budget=plan.get("budget_ms")
            if not isinstance(budget,(float,int)) or isinstance(budget,bool) or not 0<budget<=now_quota or plan["mode"] in {"wait","yield","paused","defer"}:
                boundary.wait_reason(db,str(plan.get("wake") or "等待 C5 预算"),binds_key)
                life.put(db,"slot31_wait_input",wake_key);life.put(db,"slot31_wait_until",time.time()+60)
                db.commit();return None
            deadline[0]=min(deadline[0],time.monotonic()+budget/1000)
            version=boundary.pin([binds_key,inputs])
            evidence=boundary.eligibility(db,offers,version,b,remaining())
            inputs["eligibility_version"]=version
            packet={**inputs,"evidence_by_lane":evidence}
            proposal=boundary.port_call(db,"C3",packet,version=version,budget_ms=remaining())
            evaluations=None
            if boundary.supports(b["C"],"C6"):
                evaluations=boundary.port_call(db,"C6",{},version=version,budget_ms=remaining())["output"]
            lane,decision=boundary.select(db,identifier,b,offers,evidence,proposal["output"]["candidates"],units,inputs,evaluations)
            if lane is None:
                boundary.wait_reason(db,"认知候选未通过宿主权限、预算或核验",binds_key)
                life.put(db,"slot31_wait_input",wake_key);life.put(db,"slot31_wait_until",decision.get("wake_at",time.time()+300))
                # Retain the actual rejected set, but never report a choice or score an ineligible action.
                event={"kind":"selection_deferred","topic":"宿主选择点","summary":decision["reason"]+"，等待新证据或预算回补。",
                       "status":"waiting","executed":False,"rejections":decision,"slot_bindings":b}
                decision=None;lane="waiting"
            else:
                decision["score_kind"]="geometric_port"
                decision["candidate_input_version"]=version;decision["sources"]=proposal["sources"]
                life.put(db,"slot31_wait_input","")
            remaining()
            if lane=="study":
                mode=inner3.current(db).get("mode_hint","explore")
                last=float(life.meta(db,"last_explore","0"))
                study_mode="explore" if time.time()-last>120 else ("review" if mode=="review" else "new")
                event=study3.do_work(db,mode=study_mode,should_yield=lambda:not remaining())
                if study_mode=="explore":life.put(db,"last_explore",time.time())
            elif lane=="flow":event=life.reasoning_step(db)
            elif lane=="integration":
                event=life.consolidate(db);life.put(db,"last_integration",time.time())
            elif lane=="native":event=life.native_agenda(db)
        remaining()
        if event:
            event=dict(event);event["executed_lane"]=lane
            if "receipt" in event:event["source_receipt"]=event["receipt"]
            event["receipt"]=identifier;event["gpu_reading"]=resources
            life.audit(db,identifier,event,decision=decision)
            life.put(db,"last_lane",lane)
            life.put(db,"mode",{"study":"学习","flow":"推理","integration":"整合","maintenance":"迭代","native":"复查原生问题","waiting":"等待证据"}[lane])
        else:
            db.execute("DELETE FROM evo3_assignments WHERE event_id=?",(identifier,))
            if life.meta(db,"mode")!="低功耗":life.put(db,"mode","低功耗")
        remaining();db.commit();return event
    except slots31.SlotUnavailable as exc:
        db.rollback()
        with db:
            slots31.mark_fault(db,exc,pinned=b.get(exc.slot) if b else None)
            life.put(db,"mode","宿主等待槽")
            boundary.wait_reason(db,str(exc),boundary.pin(b or {}))
        return None
    except boundary.PortDeclined as exc:
        db.rollback()
        with db:boundary.wait_reason(db,str(exc),boundary.pin(b or {}))
        return None
    except TimeoutError:
        db.rollback()
        with db:
            boundary.wait_reason(db,"后台预算耗尽，等待下一次宿主唤醒",boundary.pin(b or {}))
        return None
    except BaseException:
        db.rollback();raise

def io_work():
    with closing(service.store()) as db:
        if life.meta(db,"paused")=="1" or life.meta(db,"enabled")!="1":return
        for task,lane in [(inquiry3.work,"inquiry"),(study3.network_work,"network")]:
            b=boundary.bindings(db)
            if lane=="inquiry" and not boundary.legacy_pair(b):continue
            if active("foreground") or life.meta(db,"paused")=="1":return
            if lane=="network" and life.meta(db,"network")!="1":continue
            event=task(db)
            if event:
                identifier=str(event.get("event_id") or "io-"+uuid4().hex)
                event=dict(event,executed_lane=lane,receipt=identifier)
                with db:life.audit(db,identifier,event)
            db.commit()

def delegated_work():
    import delegated25
    with closing(service.store()) as db:
        if active("foreground") or life.meta(db,"paused")=="1" or life.meta(db,"enabled")!="1":return
        event=delegated25.pump(db)
        if event:
            key=event.get("receipt") or event.get("event_id")
            identifier="deleg-"+n.sha(n.canonical([event.get("kind"),key,event.get("summary")]).encode())[:32]
            with db:life.audit(db,identifier,dict(event,executed_lane="delegated",source_receipt=key,receipt=identifier))

def worker():
    with latch("worker",True) as first:
        if not first:return
        with closing(service.store()) as db,ThreadPoolExecutor(max_workers=2) as pool:
            db.execute("PRAGMA busy_timeout=750")
            with db:
                life.put(db,"pid",os.getpid());life.put(db,"heartbeat",time.time())
            sensor=Readout();last_version=None;future=None;delegation=None;next_deleg=0.;next_io=0.;next_work=0.;next_beat=0.;failures=0
            while True:
                now=time.monotonic()
                try:
                    if life.meta(db,"enabled")!="1":break
                    if now>=next_beat:
                        with db:life.put(db,"heartbeat",time.time())
                        next_beat=now+2
                    if future and future.done():
                        try:future.result()
                        except Exception as e:lifecycle_log("io_error",e)
                        future=None
                    if delegation and delegation.done():
                        try:delegation.result()
                        except Exception as e:lifecycle_log("delegation_error",e)
                        delegation=None
                    observed_version=db.execute("PRAGMA data_version").fetchone()[0]
                    if observed_version!=last_version:next_work=0;last_version=observed_version
                    if not active("foreground") and life.meta(db,"paused")!="1":
                        if not delegation and now>=next_deleg:
                            delegation=pool.submit(delegated_work);next_deleg=now+2.
                        if not future and now>=next_io:
                            future=pool.submit(io_work);next_io=now+60
                        if now>=next_work:
                            result=select_step(db,sensor.sample());failures=0
                            next_work=now+(1.25 if result else 6.0)
                    time.sleep(.16)
                except InterruptedError:
                    next_work=time.monotonic()+.25
                except sqlite3.OperationalError as e:
                    db.rollback()
                    if "locked" not in str(e).lower():lifecycle_log("worker_db",e)
                    time.sleep(.4)
                except Exception as exc:
                    db.rollback();failures+=1;lifecycle_log("work_error",traceback.format_exc())
                    with db:life.audit(db,"failure-"+uuid4().hex,dict(kind="worker_failure",topic="后台工作恢复",
                        summary=str(exc)[:240],failed=True,progress=False,status="failed",error=type(exc).__name__))
                    if failures>=4:raise
                    time.sleep(2)
            sensor.close()
            with db:life.put(db,"mode","已停止");life.put(db,"heartbeat",time.time())

def supervise():
    with latch("supervisor",True) as first:
        if not first:return
        history=[];proc=None;observer=None
        with closing(service.store()) as db:
            try:
                while life.meta(db,"enabled")=="1":
                    if proc is None or proc.poll() is not None:
                        now=time.time();history=[t for t in history if now-t<180]
                        if len(history)>=4:
                            lifecycle_log("restart_limit","连续异常退出，后台已暂停")
                            with db:life.put(db,"enabled",0);life.put(db,"mode","异常停止")
                            return
                        if observer:
                            try:observer.wait(timeout=4)
                            except subprocess.TimeoutExpired:pass
                        proc=spawn(Path(__file__),"worker");history.append(now)
                        with db:life.put(db,"supervisor_pid",os.getpid())
                        observer=spawn(ROOT/"host/watchdog3.py","--database",n.DB,"--log",ROOT/"evidence/life3/watchdog.jsonl","--parent",proc.pid,"--identity",n.IDENTITY)
                        lifecycle_log("worker_start",proc.pid)
                    elif observer and observer.poll() is not None:
                        observer=spawn(ROOT/"host/watchdog3.py","--database",n.DB,"--log",ROOT/"evidence/life3/watchdog.jsonl","--parent",proc.pid,"--identity",n.IDENTITY)
                    if life.meta(db,"pid")==str(proc.pid) and time.time()-float(life.meta(db,"heartbeat","0"))>120 and time.time()-history[-1]>120:
                        lifecycle_log("unresponsive",proc.pid);proc.terminate();proc.wait(timeout=8)
                    time.sleep(1)
            finally:
                if proc and proc.poll() is None:
                    try:proc.wait(timeout=48)
                    except subprocess.TimeoutExpired:proc.terminate();proc.wait(timeout=8)

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("action",choices=["worker","supervise"])
    args=p.parse_args()
    try:supervise() if args.action=="supervise" else worker()
    except Exception:
        lifecycle_log("fatal",traceback.format_exc());raise

