"""Intake 0.1.0 -> M7. Fetch one public registry and queue sourced leads; no engine admission."""
import argparse
from contextlib import closing
from datetime import datetime
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
LIB=ROOT/"learning_materials/intake/0.1.0"
ZIP_PIN="42bf47fc667363f9f61dc8944235116f5ce9044440f177a3fd993185b39a5571"
MANIFEST_PIN="4a58ccaa336ad27656af9531563edbf560ce0204c194ca3c171ebc3374c8bfdf"
FILES=("intake/__init__.py","intake/module.py","intake/net.py","intake/filter_text.py","intake/policy.py",
       "intake/schema_check.py","schema/candidate_evidence_v1.schema.json","schema/source_version_v1.schema.json",
       "schema/intake_error_v1.schema.json","MODULE.json","MANIFEST.json")
SOURCE="https://www.iana.org/assignments/http-methods/http-methods.txt"
ROBOTS="https://www.iana.org/robots.txt"
METHODS=("GET","HEAD","POST","PUT")
LINE=re.compile(r"(GET|HEAD|POST|PUT) (yes|no) (yes|no) \[RFC 9110, Section 9\.3\.[1-9]\]\Z")
FORMAT="zaizai-intake-m7-v1"

def sha(data):
    return hashlib.sha256(data.encode() if isinstance(data,str) else data).hexdigest()

def check(ok,detail):
    if not ok:raise ValueError(detail)

def report(value):
    print(json.dumps(value,ensure_ascii=False,indent=2))

def manifest(raw):
    check(sha(raw)==MANIFEST_PIN,"捕捞包清单不匹配")
    d=json.loads(raw)
    return {x["path"]:x for x in d["files"]}

def verify_files():
    pins=manifest((LIB/"MANIFEST.json").read_bytes())
    for name in FILES:
        if name=="MANIFEST.json":continue
        data=(LIB/name).read_bytes()
        check(len(data)==pins[name]["bytes"] and sha(data)==pins[name]["sha256"],"本机捕捞文件与上游不符 "+name)

def install(archive):
    check(archive.is_file() and sha(archive.read_bytes())==ZIP_PIN,"未知的捕捞发布包")
    with ZipFile(archive) as z:
        pins=manifest(z.read("MANIFEST.json"))
        check(len(z.namelist())==len(pins)+1 and set(z.namelist())==set(pins)|{"MANIFEST.json"},"压缩包与清单不同")
        for name,item in pins.items():
            data=z.read(name)
            check(len(data)==item["bytes"] and sha(data)==item["sha256"],"原始文件损坏 "+name)
        if not LIB.exists():
            LIB.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="intake-install-",dir=LIB.parent) as tmp:
                stage=Path(tmp)/"verified";stage.mkdir()
                for name in FILES:
                    p=stage/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(z.read(name))
                os.rename(stage,LIB)
    verify_files()
    return {"release":"0.1.0","zip_sha256":ZIP_PIN,"upstream_files_verified":len(pins),"installed_files":list(FILES),"root":str(LIB)}

def upstream():
    verify_files()
    sys.path.insert(0,str(LIB))
    try:
        module=importlib.import_module("intake.module")
        net=importlib.import_module("intake.net")
        schema=importlib.import_module("intake.schema_check")
        check(Path(module.__file__).resolve()==(LIB/"intake/module.py").resolve(),"捕捞模块来自其他位置")
        return module,net,schema
    finally:
        sys.path.pop(0)

def packet_digest(obj):
    return sha(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")))

def capture(out):
    check(not out.exists() and out.parent.is_dir(),"输出文件需为尚不存在的文件")
    module,net,_=upstream()
    class FixedRegistry(net.FetchClient):
        def __init__(self):
            super().__init__(allow_private=False,min_interval=1.0,timeout=7,max_bytes=65536)
            self.access=[]
        def _once(self,url):
            if url not in (SOURCE,ROBOTS) or len(self.access)>=2:
                raise net.FetchError("bypass_refused","仅取固定登记表与该站 robots")
            self.access.append(url)
            response=super()._once(url)
            if 300<=response["status"]<400:
                raise net.FetchError("unread_source","固定来源发生重定向")
            return response
        def get(self,url):
            fetched=super().get(url)
            if fetched["status"]==200 and fetched["kind"]=="text" and not fetched["truncated"]:
                # Four factual registry rows are sufficient for this bridge. No full-body archival.
                fetched["lines"]=[line for line in fetched["lines"] if LINE.fullmatch(line)]
                matched=[LINE.fullmatch(line)[1] for line in fetched["lines"]]
                check(len(matched)==4 and set(matched)==set(METHODS),"固定登记表的格式已改变")
            return fetched
    with tempfile.TemporaryDirectory(prefix="intake-raw-candidates-") as tmp:
        app=module.IntakeModule(tmp,online=True,allow_private=False,request_budget=2,min_interval=1.)
        app.client=FixedRegistry()
        result=app.run_url(SOURCE)
        check(result.get("status")=="accepted","捕获未得到候选："+json.dumps(result.get("error",{}),ensure_ascii=False))
        check(not app.executed_commands and app.admit_calls==app.formal_writes==0,"原捕获结果有未预期的效果")
        check(not app.validate_files(),"原包对生成候选的协议检查失败")
        candidates=[json.loads((Path(tmp)/"candidates"/(key+".json")).read_bytes()) for key in result["candidate_ids"]]
        packet={"format":FORMAT,"archive_sha256":ZIP_PIN,"version":result["version"],"candidates":candidates,
                "requests":app.client.access,"risk_audits":result["audits"],"formal_write":False,"admit_called":False}
    validate(packet)
    with out.open("x",encoding="utf8") as f:json.dump(packet,f,ensure_ascii=False,indent=2)
    return {"packet":str(out),"packet_sha256":packet_digest(packet),"source":SOURCE,
            "version":packet["version"]["content_sha256"],"candidates":len(candidates),"requests":packet["requests"],
            "scope":"四条 IANA 方法登记摘录；无自动接纳"}

def validate(packet):
    _,_,schema=upstream()
    check(packet.get("format")==FORMAT and packet.get("archive_sha256")==ZIP_PIN,"数据包协议或发布版本不符")
    check(packet.get("admit_called") is False and packet.get("formal_write") is False,"数据包不是只读候选")
    check(packet.get("requests")==[ROBOTS,SOURCE],"来源不是固定官方登记表")
    def contract(d,kind):
        shape=json.loads((LIB/"schema"/(kind+".schema.json")).read_bytes())
        failures=schema.check(d,shape,kind)
        check(not failures,"字段校验失败："+str(failures[:1]))
    v=packet["version"]
    contract(v,"source_version_v1")
    check(v["url"]==SOURCE and v["fetch_status"]=="fetched" and v["origin_role"]=="independent" and v["robots"]=="allowed",
          "实际读取、来源或 robots 回执不符合")
    check(re.fullmatch(r"[0-9a-f]{64}",v["content_sha256"]) and v["version_seq"]>=1,"原文版本无效")
    check(datetime.fromisoformat(v["fetched_at"].replace("Z","+00:00")).tzinfo is not None,"采集时点缺少时区")
    family="fam:src:"+SOURCE
    version="srcver-"+sha(SOURCE+"|"+v["content_sha256"])[:16]
    check(v["evidence_family_id"]==family and v["source_version_id"]==version,"来源族或版本编号不一致")
    rows={}
    check(isinstance(packet["candidates"],list) and len(packet["candidates"])==len(METHODS),"候选集合不完整")
    for c in packet["candidates"]:
        contract(c,"candidate_evidence_v1")
        p=c["proposition"];loc=c["locator"];guard=c["cl_safe"];q=p["text"]
        mat=LINE.fullmatch(q)
        check(mat and mat[1] not in rows,"候选摘录不符合登记表结构")
        check(loc["url"]==SOURCE and loc["quote_sha256"]==sha(q) and loc["recheckable"] is True,"摘录位置或摘要不符")
        check(c["evidence_family_id"]==family and c["source_version_id"]==version and c["candidate_id"]=="cand-"+sha(version+q)[:16],"候选编号或来源冲突")
        check(c["belief_status"]=="candidate_only" and c["formal_write"] is False and c["body_policy"]=="retain","候选状态不允许")
        check(c["risk"]["disposition"]=="analyze_ok" and c["retraction"]["relation"]=="none","材料已撤回或尚不可收录")
        check(guard["expressible"] is False and guard["executable_claim"] is False and guard["cl_status"]=="NOT_RUN"
              and guard["admit_called"] is False and guard["state"]=="STATE_NOT_ATTACHED","候选自称已进入引擎")
        check(p["scope"]["subject"]==SOURCE and p["polarity"]=="background" and p["speech_act"]=="verifiable","引用未经问题对齐")
        rows[mat[1]]=(q,c["candidate_id"],loc["quote_sha256"])
    check(set(rows)==set(METHODS),"候选方法集合不符")
    return rows

def load_m7():
    sys.path.insert(0,str(ROOT/"host"))
    try:
        return importlib.import_module("study3")
    finally:sys.path.pop(0)

def queue(db,packet):
    rows=validate(packet)
    study=load_m7()
    v=packet["version"]
    if db.in_transaction:raise ValueError("桥接需要空闲数据库连接")
    db.execute("BEGIN IMMEDIATE")
    try:
        # TXT and CSV are two renderings of one IANA registry.
        sid=study.source_id(db,study.METHOD_URL,v["content_sha256"],SOURCE)
        active=db.execute("SELECT active FROM study3_source WHERE id=?",(sid,)).fetchone()[0]
        check(active,"此来源版本已撤回，不重新入队")
        added=0
        receipt=[]
        for method in METHODS:
            quote,cid,pin=rows[method]
            claim="待对齐的 IANA 方法登记摘录 "+method
            locator="Method="+method+"; intake="+cid
            note=json.dumps({"quote":quote,"quote_sha256":pin,"candidate_id":cid,"family":v["evidence_family_id"],
                             "upstream_version":v["source_version_id"],"fetched_at":v["fetched_at"],
                             "belief_status":"candidate_only","polarity":"background"},ensure_ascii=False,sort_keys=True)
            count=db.total_changes
            ob=study.observe(db,sid,claim,1,note,locator,"intake_lead")
            added+=db.total_changes-count
            rec=db.execute("SELECT stage,kind FROM study3_observation WHERE id=?",(ob,)).fetchone()
            check(rec and rec[1]=="intake_lead" and rec[0] in {"candidate","lead"},"同一材料存在不相容的接纳状态")
            receipt.append({"method":method,"candidate":cid,"m7_observation":ob,"stage":rec[0]})
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return {"source_id":sid,"family":study.METHOD_URL,"source_version":v["content_sha256"],"added":added,
            "packet_sha256":packet_digest(packet),"observations":receipt,"formal_claims_added":0,"engine_calls":0}

def read_packet(path):
    check(path.is_file() and path.stat().st_size<=100000,"数据包缺失或超出固定协议大小")
    return json.loads(path.read_bytes())

def self_check(packet):
    study=load_m7()
    with tempfile.TemporaryDirectory(prefix="intake-m7-proof-") as tmp,closing(sqlite3.connect(Path(tmp)/"check.sqlite")) as db:
        db.row_factory=sqlite3.Row
        with db:study.setup(db)
        first=queue(db,packet);again=queue(db,packet)
        check(first["added"]==4 and again["added"]==0,"重复包增加了数据")
        with db:
            for result in first["observations"]:
                row=db.execute("""SELECT o.*,s.uri,s.version FROM study3_observation o JOIN study3_source s ON s.id=o.source_id
                                  WHERE o.id=?""",(result["m7_observation"],)).fetchone()
                study.review_observation(db,row)
        stages=dict(db.execute("SELECT stage,count(*) FROM study3_observation GROUP BY stage"))
        claims=db.execute("SELECT count(*) FROM study3_judgment").fetchone()[0]
        check(stages=={"lead":4} and claims==0,"材料发生非预期的可信度提升")
        with db:study.invalidate(db,first["source_id"])
        try:queue(db,packet)
        except ValueError as exc:
            check("撤回" in str(exc),"拒绝原因不是撤回")
        else:raise ValueError("失效来源被重新激活")
        return {"first":first,"replay_added":again["added"],"after_ordinary_m7_review":stages,"judgments":claims,
                "withdrawal_respected":True,"operational_db_written":False}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="op",required=True)
    ins=sub.add_parser("install");ins.add_argument("archive",type=Path)
    fetch=sub.add_parser("capture");fetch.add_argument("--out",type=Path,required=True)
    test=sub.add_parser("check");test.add_argument("packet",type=Path)
    write=sub.add_parser("queue");write.add_argument("packet",type=Path);write.add_argument("--db",required=True,type=Path)
    args=parser.parse_args()
    if args.op=="install":
        result=install(args.archive)
    elif args.op=="capture":
        result=capture(args.out.resolve())
    elif args.op=="check":
        result=self_check(read_packet(args.packet))
    else:
        path=args.db.resolve(strict=True)
        with closing(sqlite3.connect(path.as_uri()+"?mode=rw",uri=True,timeout=8)) as db:
            result=queue(db,read_packet(args.packet))
    report(result)

if __name__=="__main__":main()
