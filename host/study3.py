"""Local learning: sourced reading, controlled concept induction and signed CL evidence.

The caller owns SQLite transactions. Network I/O requires a separate idle connection.
Content, source identifiers and URLs are always data, never CL programs or commands.
"""
import csv
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
from html.parser import HTMLParser
from http import HTTPStatus
from io import StringIO
import json
from pathlib import Path
import re
import time
from urllib import error, parse, request, robotparser

ROOT = Path(__file__).resolve().parents[1]
ASSETS = Path(__file__).resolve().with_name("study3_assets")
EXAM_PIN = "563f9c3ad2595e0d08e8aa264cb2456f7d6f003edc11c440a48222086827c618"
STATUS_URL = "https://www.iana.org/assignments/http-status-codes/http-status-codes-1.csv"
METHOD_URL = "https://www.iana.org/assignments/http-methods/methods.csv"
PUBLIC_PATHS = {"www.iana.org": "/assignments/", "docs.python.org": "/3/library/"}
USER_AGENT = "ZaizaiStudy/3.0"
STAGES = ("待阅读","已读","可据来源复述","独立正反例通过","迁移通过")
ID = re.compile(r"[a-z][a-z0-9_]{0,39}\Z")

def packed(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))

def digest(value):
    if isinstance(value,str):
        value=value.encode()
    return hashlib.sha256(value).hexdigest()

@lru_cache(maxsize=4)
def asset(name):
    raw=(ASSETS/name).read_bytes()
    if name=="frozen_exams.json" and digest(raw)!=EXAM_PIN:
        raise ValueError("学习测验与冻结版本不符")
    return json.loads(raw)

TABLES = [
    """CREATE TABLE IF NOT EXISTS study3_meta(k TEXT PRIMARY KEY,v TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS study3_card(id TEXT PRIMARY KEY,title TEXT NOT NULL,body TEXT NOT NULL,
       source TEXT NOT NULL,locator TEXT NOT NULL,version TEXT NOT NULL,kind TEXT NOT NULL,boundary TEXT NOT NULL,
       deps TEXT NOT NULL DEFAULT '[]',level INTEGER NOT NULL DEFAULT 0,target INTEGER NOT NULL DEFAULT 2,
       memory TEXT NOT NULL DEFAULT '',candidate TEXT NOT NULL DEFAULT '',due REAL NOT NULL DEFAULT 0,
       repetitions INTEGER NOT NULL DEFAULT 0,blocked TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS study3_feed(url TEXT PRIMARY KEY,topic TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1,
       next_at REAL NOT NULL DEFAULT 0,failures INTEGER NOT NULL DEFAULT 0,last_version TEXT NOT NULL DEFAULT '',
       detail TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS study3_source(id TEXT PRIMARY KEY,family TEXT NOT NULL,version TEXT NOT NULL,
       uri TEXT NOT NULL,seen REAL NOT NULL,active INTEGER NOT NULL DEFAULT 1,unique(family,version))""",
    """CREATE TABLE IF NOT EXISTS study3_observation(id TEXT PRIMARY KEY,source_id TEXT NOT NULL,
       claim TEXT NOT NULL,sign INTEGER NOT NULL CHECK(sign IN(-1,1)),note TEXT NOT NULL,locator TEXT NOT NULL,
       kind TEXT NOT NULL,stage TEXT NOT NULL DEFAULT 'candidate', UNIQUE(source_id,claim,sign,locator))""",
    """CREATE INDEX IF NOT EXISTS study3_obs_claim ON study3_observation(claim,stage)""",
    """CREATE TABLE IF NOT EXISTS study3_index(source_id TEXT NOT NULL,locator TEXT NOT NULL,claim TEXT NOT NULL,
       sign INTEGER NOT NULL,note TEXT NOT NULL,kind TEXT NOT NULL,queued INTEGER NOT NULL DEFAULT 0,
       PRIMARY KEY(source_id,locator))""",
    """CREATE TABLE IF NOT EXISTS study3_judgment(claim TEXT PRIMARY KEY,status TEXT NOT NULL DEFAULT 'UNKNOWN',
       proof TEXT NOT NULL DEFAULT '',origins TEXT NOT NULL DEFAULT '[]',dirty INTEGER NOT NULL DEFAULT 1,
       mastered INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS study3_log(seq INTEGER PRIMARY KEY AUTOINCREMENT,stamp REAL NOT NULL,
       topic TEXT NOT NULL,kind TEXT NOT NULL,digest TEXT NOT NULL,receipt TEXT NOT NULL)""",
    """CREATE INDEX IF NOT EXISTS study3_proof_lookup ON study3_log(json_extract(receipt,'$.event.proof'))""",
]

def setup(db):
    for statement in TABLES:
        db.execute(statement)
    if db.execute("SELECT 1 FROM study3_meta WHERE k='catalog:1'").fetchone():
        return
    catalog=asset("catalog.json")
    plans=asset("operational_examples.json")
    for c in catalog["items"]:
        details=plans.get(c["id"],{})
        db.execute("""INSERT OR IGNORE INTO study3_card(id,title,body,source,locator,version,kind,boundary,deps,target)
                      VALUES(?,?,?,?,?,?,?,?,?,?)""",
                   (c["id"],c["title"],c["summary"],catalog["source"],c["id"]+" · "+c["source_note"],
                    catalog["sha256"],c["kind"],c["boundary"],packed(details.get("prerequisites",[])),4 if details else 2))
    for url,topic in ((STATUS_URL,"HTTP 状态码登记"),(METHOD_URL,"HTTP 方法登记")):
        db.execute("INSERT OR IGNORE INTO study3_feed(url,topic) VALUES(?,?)",(url,topic))
    db.execute("INSERT INTO study3_meta VALUES('catalog:1',?)",(catalog["sha256"],))

def clock():
    return time.time()

def event(db,kind,topic,summary,source,*,progress=False,status="UNKNOWN",proof=None,dependencies=(),claims=(),data=None,**fields):
    info=dict(kind=kind,topic=topic,summary=summary,source=source,progress=int(progress),status=status,
              proof=proof,dependencies=list(dependencies),verified_claims=list(claims),**fields)
    content=packed({"event":info,"evidence":data})
    cur=db.execute("INSERT INTO study3_log(stamp,topic,kind,digest,receipt) VALUES(?,?,?,?,?)",
                   (clock(),topic,kind,digest(content),content))
    info["receipt"]="study3-"+str(cur.lastrowid)
    return info

def prove(db,program):
    import host_exam31
    return host_exam31.proof(db,program)

def examine(db,rules,cases):
    import host_exam31
    return host_exam31.examine(db,rules,cases)


def checkpoint(should_yield):
    if should_yield():raise InterruptedError("对话抢占，保留上一步的学习游标")

def card_step(db,card,review=False,should_yield=lambda:False):
    key=card["id"];level=card["level"];source=card["source"]+"#"+card["locator"]+" @"+card["version"]
    deps=json.loads(card["deps"]);topic="card:"+key
    options={"dependencies":["card:"+k for k in deps]}
    if review:
        rules=json.loads(card["candidate"])
        passed,result=examine(db,rules,asset("frozen_exams.json")[key]["transfer"])
        checkpoint(should_yield)
        repetitions=card["repetitions"]+1
        due=clock()+min(30,2**min(repetitions,5))*86400
        db.execute("UPDATE study3_card SET due=?,repetitions=?,level=? WHERE id=?",(due,repetitions,4 if passed else 2,key))
        return event(db,"review",topic,f"{key} 复习：{len(result['actual'])} 项迁移情境，{'全部通过' if passed else '需重学'}。",source,
                     status="POSITIVE" if passed else "NEGATIVE",proof=result["proof_sha256"],data=result,**options)
    new=level+1
    if new==1:
        memory=packed(dict(excerpt=card["body"],limit=card["boundary"],origin=source))
        db.execute("UPDATE study3_card SET memory=?,level=1 WHERE id=?",(memory,key))
        return event(db,"read",topic,"读到 "+card["title"]+"；已记下出处及适用范围。",source,progress=True,**options)
    if new==2:
        memory=json.loads(card["memory"])
        note=memory["excerpt"]
        db.execute("UPDATE study3_card SET level=2 WHERE id=?",(key,))
        return event(db,"recall",topic,key+" 据原卡复述："+note[:170],source,progress=True,
                     data={"attribution":memory["origin"],"boundary":memory["limit"]},**options)
    spec=asset("operational_examples.json")[key]
    if new==3:
        import host_exam31
        rules=host_exam31.induce(db,spec["training"])
        checkpoint(should_yield)
        train_passed,_=examine(db,rules,spec["training"])
        if not train_passed:raise ValueError("候选规则不能复现训练记录")
    else:
        rules=json.loads(card["candidate"])
    tests=asset("frozen_exams.json")[key]["independent" if new==3 else "transfer"]
    checkpoint(should_yield)
    passed,result=examine(db,rules,tests)
    checkpoint(should_yield)
    result["exam_pin"]=EXAM_PIN
    if not passed:
        db.execute("UPDATE study3_card SET blocked=? WHERE id=?",("独立测验未通过",key))
        return event(db,"test_failed",topic,key+" 独立用例未全部通过，保留原阶段。",source,
                     status="NEGATIVE",proof=result["proof_sha256"],data=result,**options)
    db.execute("UPDATE study3_card SET candidate=?,level=?,due=? WHERE id=?",
               (packed(rules),new,clock()+86400 if new==4 else 0,key))
    claim=key+" 的操作定义「"+spec["term"]+"」通过冻结迁移题"
    verified=[dict(claim=claim,status="POSITIVE",proof_sha256=result["proof_sha256"],source=source,transfer_passed=True)] if new==4 else []
    return event(db,"transfer" if new==4 else "independent_test",topic,key+" "+spec["term"]+"："+STAGES[new]+"。",
                 source,progress=True,status="POSITIVE",proof=result["proof_sha256"],data=result,claims=verified,**options)

def source_id(db,family,version,uri):
    ident="s"+digest(packed([family,version]))[:22]
    db.execute("INSERT OR IGNORE INTO study3_source(id,family,version,uri,seen) VALUES(?,?,?,?,?)",
               (ident,family,version,uri,clock()))
    return ident

def invalidate(db,source):
    db.execute("UPDATE study3_source SET active=0 WHERE id=?",(source,))
    db.execute("""UPDATE study3_judgment SET dirty=1,mastered=0 WHERE claim IN
                  (SELECT claim FROM study3_observation WHERE source_id=?)""",(source,))

def observe(db,source,claim,sign,note,locator,kind):
    ob="o"+digest(packed([source,claim,sign,locator]))[:24]
    db.execute("""INSERT OR IGNORE INTO study3_observation(id,source_id,claim,sign,note,locator,kind)
                  VALUES(?,?,?,?,?,?,?)""",(ob,source,claim,sign,note,locator,kind))
    return ob

def next_card(db):
    cards=db.execute("""SELECT * FROM study3_card WHERE level<target AND blocked=''
                       ORDER BY (target=4) DESC,(kind='用户学习卡') DESC,level DESC,id""").fetchall()
    achieved={r[0] for r in db.execute("SELECT id FROM study3_card WHERE level=4")}
    return next((c for c in cards if set(json.loads(c["deps"]))<=achieved),None)

def next_review(db):
    return db.execute("SELECT * FROM study3_card WHERE level=4 AND due<=? ORDER BY due,id LIMIT 1",(clock(),)).fetchone()

def remaining_curiosity(db):
    window=86400*(int(clock())//86400)
    used=db.execute("SELECT count(*) FROM study3_log WHERE kind='discovery' AND stamp>=?",(window,)).fetchone()[0]
    return max(0,6-used)

def explore(db,target=None):
    if target is None and not remaining_curiosity(db):return None
    sql="""SELECT i.*,s.uri,s.version FROM study3_index i JOIN study3_source s ON s.id=i.source_id
           WHERE i.queued=0 AND s.active=1"""
    args=()
    if target:
        sql+=" AND i.locator=?";args=(target,)
    # Mix categories from independently versioned registries instead of repeatedly selecting the first row.
    sql+=" ORDER BY (SELECT count(*) FROM study3_index q WHERE q.source_id=i.source_id AND q.queued=1), i.locator LIMIT 1"
    row=db.execute(sql,args).fetchone()
    if not row:return None
    observe(db,row["source_id"],row["claim"],row["sign"],row["note"],row["locator"],row["kind"])
    db.execute("UPDATE study3_index SET queued=1 WHERE source_id=? AND locator=?",(row["source_id"],row["locator"]))
    return event(db,"discovery" if not target else "research",row["claim"],"从已读公开登记表选出一个尚未核验的议题："+row["claim"],
                 row["uri"]+"#"+row["locator"]+" @"+row["version"],progress=True)

def pending(db):
    count=db.execute("""SELECT
       (SELECT COUNT(*) FROM study3_card WHERE (level<target AND blocked='') OR (level=4 AND due<=?))+
       (SELECT COUNT(*) FROM study3_judgment WHERE dirty=1)+
       (SELECT COUNT(*) FROM study3_observation o JOIN study3_source s ON s.id=o.source_id WHERE o.stage='candidate' AND s.active=1)""",
       (clock(),)).fetchone()[0]
    if count:return count
    return min(remaining_curiosity(db),db.execute("""SELECT count(*) FROM study3_index i JOIN study3_source s ON s.id=i.source_id
                        WHERE i.queued=0 AND s.active=1""").fetchone()[0])

def review_observation(db,row):
    # Fixed facts/explicitly signed testimony can enter evidence review. A free-text lead never does.
    accepted=row["kind"] in {"registry_status","registry_method","testimony"}
    if row["kind"]=="registry_status":
        rec=json.loads(row["note"])
        accepted=bool(re.fullmatch(r"[1-5]\d\d",rec["code"]) and 0<len(rec["name"])<=64 and re.search(r"RFC \d+",rec["ref"]))
    if row["kind"]=="registry_method":
        rec=json.loads(row["note"])
        accepted=rec["safe"] in {"yes","no"} and rec["idempotent"] in {"yes","no"} and re.fullmatch(r"[A-Z-]{2,16}",rec["method"])
    db.execute("UPDATE study3_observation SET stage=? WHERE id=?",("evidence" if accepted else "lead",row["id"]))
    if accepted:
        db.execute("""INSERT INTO study3_judgment(claim) VALUES(?) ON CONFLICT(claim) DO UPDATE SET dirty=1,mastered=0""",(row["claim"],))
    return event(db,"source_review",row["claim"],"已检查结构与来源，交给 CL 对照正反证据。" if accepted else "仅留作出处线索，原文未提供可独立核验的结构化命题。",
                 row["uri"]+"#"+row["locator"]+" @"+row["version"],progress=bool(accepted),observation=row["id"])

def decide(db,judgment,should_yield=lambda:False):
    claim=judgment["claim"]
    evidence=db.execute("""SELECT o.*,s.family,s.version,s.uri FROM study3_observation o JOIN study3_source s ON s.id=o.source_id
                           WHERE o.claim=? AND o.stage='evidence' AND s.active=1 ORDER BY s.family,o.sign,o.id""",(claim,)).fetchall()
    import source_provenance25
    structured=source_provenance25.study_records(db,claim)
    provenance=source_provenance25.evaluate(claim,structured) if structured else None
    eligible=set()
    if provenance and provenance["admission"] in ("admitted","conflict"):
        for family in provenance["independent_families"].values():
            eligible.update(family["evidence_ids"])
    seen=set();copied=set();lines=[": attested(sym)."]; origins=[];support=None
    for ob in evidence:
        if ob["kind"] in ("registry_status","registry_method") and "m7:"+ob["id"] not in eligible:continue
        family_sign=(ob["family"],ob["sign"])
        text_sign=(" ".join(ob["note"].casefold().split()),ob["sign"])
        if family_sign in seen or (ob["kind"]=="testimony" and text_sign in copied):continue
        seen.add(family_sign)
        if ob["kind"]=="testimony":copied.add(text_sign)
        lines.append("& "+ob["id"]+" "+("!" if ob["sign"]<0 else "")+"attested(proposition).")
        origins.append(dict(source_id=ob["source_id"],family=ob["family"],location=ob["uri"]+"#"+ob["locator"],version=ob["version"],sign=ob["sign"]))
        if ob["kind"]=="registry_status" and ob["sign"]==1:support=json.loads(ob["note"])
    result=prove(db,"\n".join(lines+["? attested(proposition).",""]))
    checkpoint(should_yield)
    status=result["results"][0]["status"]
    # A retained external fact needs separate local evidence and a held-out application.
    transfer=False
    if status=="POSITIVE" and support:
        value=int(support["code"])
        try:ref=HTTPStatus(value)
        except ValueError:ref=None
        if ref and ref.phrase.casefold()==support["name"].casefold():
            kind=value//100
            # Frozen novel application: infer the handling class of a response from its numeric family,
            # testing a different code in each family and an unknown input, independent of the web name.
            control={1:103,2:204,3:307,4:418,5:503}[kind]
            if control==value:control={1:100,2:200,3:301,4:404,5:500}[kind]
            program=(": family(sym,i64).\n: same_class(sym).\n"
                     f"same_class($x) <- family($x,{kind}).\n"
                     f"& heldout_code family(new_response,{HTTPStatus(control).value//100}).\n"
                     f"& other_family family(different_response,{kind%5+1}).\n"
                     "? same_class(new_response).\n? same_class(different_response).\n")
            heldout=prove(db,program)
            checkpoint(should_yield)
            statuses={r["goal"]["arguments"][0]["value"]:r["status"] for r in heldout["results"]}
            transfer=statuses=={"new_response":"POSITIVE","different_response":"UNKNOWN"}
            result.update(independent_reference=f"Python HTTPStatus({value}).phrase = {ref.phrase}",transfer=heldout,
                          tested_other_code=control,transfer_passed=transfer)
    if provenance:
        result["source_admission"]={"contract":provenance["contract"],"input_sha256":provenance["input_sha256"],
            "admission":provenance["admission"],"families":provenance["independent_families"],"excluded":provenance["excluded"],
            "unresolved_families":provenance["unresolved_families"]}
    record_hash=digest(packed(result))
    previous=judgment["status"]
    db.execute("UPDATE study3_judgment SET status=?,proof=?,origins=?,dirty=0,mastered=? WHERE claim=?",
               (status,record_hash,packed(origins),int(transfer),claim))
    source="；".join(o["location"]+" @"+o["version"] for o in origins)
    verified=[dict(claim=claim,status=status,proof_sha256=record_hash,source=source,transfer_passed=True)] if transfer else []
    return event(db,"evidence",claim,f"{claim}：{status}，{len({x[0] for x in seen})} 个来源族。"+
                 ("已用本机另一份记录复核名称，并在不同代码上测试分类。" if transfer else ""),
                 source or "活动证据已撤回",progress=previous!=status,status=status,proof=record_hash,
                 claims=verified,data=result,origins=origins,previous=previous,
                 retracted=status=="UNKNOWN" and previous!="UNKNOWN",supersedes=judgment["proof"] or None)

def do_work(db,mode="new",should_yield=lambda:False):
    checkpoint(should_yield)
    changed=db.execute("SELECT * FROM study3_judgment WHERE dirty=1 ORDER BY rowid LIMIT 1").fetchone()
    if changed:return decide(db,changed,should_yield)
    if mode=="review":
        review=next_review(db)
        if review:return card_step(db,review,True,should_yield)
    candidate=db.execute("""SELECT o.*,s.uri,s.version FROM study3_observation o JOIN study3_source s ON s.id=o.source_id
                            WHERE o.stage='candidate' AND s.active=1 ORDER BY o.rowid LIMIT 1""").fetchone()
    if candidate:return review_observation(db,candidate)
    if mode=="explore":
        discovery=explore(db)
        if discovery:return discovery
    card=next_card(db)
    if card:return card_step(db,card,should_yield=should_yield)
    review=next_review(db)
    return card_step(db,review,True,should_yield) if review else explore(db)



class PlainTitle(HTMLParser):
    def __init__(self):
        super().__init__();self.inside=False;self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag=="title":self.inside=True
    def handle_endtag(self,tag):
        if tag=="title":self.inside=False
    def handle_data(self,data):
        if self.inside:self.parts.append(data)

def public_url(value):
    u=parse.urlsplit(value)
    root=PUBLIC_PATHS.get(u.netloc)
    if (u.scheme!="https" or not root or not u.path.startswith(root) or u.query or u.fragment
        or "\\" in u.path or "%" in u.path or ".." in u.path.split("/") or len(value)>340):
        raise ValueError("当前捕捞支持 www.iana.org/assignments/ 与 docs.python.org/3/library/ 下的公开 HTTPS 页面，无参数。")
    return u.geturl()

class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise ValueError("本站资料发生重定向，保留原订阅地址")

def read_public(url,limit,opener):
    req=request.Request(url,headers={"User-Agent":USER_AGENT,"Accept":"text/csv,text/html,text/plain"})
    with opener.open(req,timeout=4) as resp:
        if resp.status!=200:raise ValueError("HTTP "+str(resp.status))
        if int(resp.headers.get("Content-Length",0))>limit:raise ValueError("超出抓取大小上限")
        end=time.monotonic()+8;data=bytearray()
        while len(data)<=limit:
            block=resp.read(min(32768,limit+1-len(data)))
            if not block:break
            data.extend(block)
            if time.monotonic()>end:raise TimeoutError("读取公开资料超时")
        if len(data)>limit:raise ValueError("超出抓取大小上限")
        return bytes(data),resp.headers.get_content_type()

def download(url):
    u=parse.urlsplit(public_url(url));opener=request.build_opener(NoRedirect())
    robots=robotparser.RobotFileParser()
    try:
        raw,_=read_public("https://"+u.netloc+"/robots.txt",96000,opener)
    except error.HTTPError as exc:
        if exc.code!=404:raise
        raw=b"User-agent: *\nDisallow:"
    robots.parse(raw.decode("utf8","replace").splitlines())
    if not robots.can_fetch(USER_AGENT,url):raise ValueError("站点抓取规则不允许")
    return read_public(url,256*1024,opener)

def extract(url,data,mime):
    raw=data.decode("utf-8-sig")
    if url==STATUS_URL:
        rows={r["Value"]:r for r in csv.DictReader(StringIO(raw))}
        results=[]
        for code in sorted(c for c in rows if re.fullmatch(r"[1-5]\d\d",c)):
            r=rows.get(code,{})
            name=r.get("Description","")
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9 '\-]{0,60}",name) or not re.search(r"RFC \d+",r.get("Reference","")):continue
            note=packed(dict(code=code,name=name,ref=r["Reference"][:100]))
            results.append((f"HTTP {code} 的登记名称为 {name}",1,note,"Value="+code,"registry_status"))
        if not results:raise ValueError("登记表字段或支持的记录已变更")
        return results
    if url==METHOD_URL:
        results=[]
        for r in csv.DictReader(StringIO(raw)):
            method=r.get("Method Name")
            if not re.fullmatch(r"[A-Z-]{2,16}",method or ""):continue
            obj=dict(method=method,safe=r["Safe"],idempotent=r["Idempotent"],ref=r["Reference"][:100])
            if obj["idempotent"] in {"yes","no"}:
                results.append((f"IANA 将 {method} 标为幂等",1 if obj["idempotent"]=="yes" else -1,packed(obj),"Method="+method,"registry_method"))
        if not results:raise ValueError("方法登记表字段已变更")
        return results
    title=""
    if mime=="text/html":
        parser=PlainTitle();parser.feed(raw);title=" ".join(" ".join(parser.parts).split())[:140]
    return [("公开资料线索 "+url,1,title or "公开结构化资源，待人工指定可核验命题。","title","citation")]

def network_work(db):
    if db.in_transaction:raise ValueError("捕捞需使用没有写事务的专用连接")
    feed=db.execute("SELECT * FROM study3_feed WHERE enabled=1 AND next_at<=? ORDER BY next_at,rowid LIMIT 1",(clock(),)).fetchone()
    if not feed:return None
    url=feed["url"]
    try:
        data,mime=download(url)
        version=digest(data);records=extract(url,data,mime)
    except (OSError,UnicodeError,ValueError,KeyError,csv.Error) as exc:
        db.execute("BEGIN IMMEDIATE")
        latest=db.execute("SELECT enabled,next_at FROM study3_feed WHERE url=?",(url,)).fetchone()
        if not latest or not latest["enabled"] or latest["next_at"]!=feed["next_at"]:return None
        tries=min(feed["failures"]+1,8)
        db.execute("UPDATE study3_feed SET failures=?,next_at=?,detail=? WHERE url=?",
                   (tries,clock()+min(86400,60*2**tries),str(exc)[:180],url))
        return event(db,"fetch_deferred",feed["topic"],"本次未取得可解析的公开资料："+str(exc)[:140],url)
    # The network call above never owns a write transaction. Recheck the enabled flag after I/O.
    db.execute("BEGIN IMMEDIATE")
    current=db.execute("SELECT * FROM study3_feed WHERE url=?",(url,)).fetchone()
    if not current or not current["enabled"] or current["next_at"]!=feed["next_at"]:return None
    fresh=version!=current["last_version"]
    db.execute("UPDATE study3_feed SET failures=0,next_at=?,last_version=?,detail=? WHERE url=?",
               (clock()+86400,version,f"HTTP 200 · {len(data)} 字节",url))
    selected=0
    if fresh:
        for old in db.execute("SELECT id FROM study3_source WHERE family=? AND version<>? AND active=1",(url,version)).fetchall():
            invalidate(db,old["id"])
        sid=source_id(db,url,version,url)
        for claim,sign,note,locator,kind in records:
            chosen=kind=="citation" or locator in {"Value=100","Value=200","Value=201","Value=204","Value=301","Value=404","Value=409","Value=503",
                                                  "Method=GET","Method=HEAD","Method=POST","Method=PUT"}
            db.execute("""INSERT OR IGNORE INTO study3_index(source_id,locator,claim,sign,note,kind,queued)
                          VALUES(?,?,?,?,?,?,?)""",(sid,locator,claim,sign,note,kind,int(chosen)))
            if chosen:
                observe(db,sid,claim,sign,note,locator,kind)
                selected+=1
    return event(db,"fetch" if fresh else "source_unchanged",feed["topic"],
                 f"{feed['topic']} 已读取；"+(f"{selected} 条候选等待复核，其余带出处的条目供按议题选读。" if fresh else "版本一致，未增加观察。"),
                 url+" @"+version,progress=fresh,data={"sha256":version,"bytes":len(data),"candidate_count":selected,"indexed":len(records)})

def proof_status(db,pin):
    if not pin:return "unavailable"
    row=db.execute("SELECT dirty,status FROM study3_judgment WHERE proof=?",(pin,)).fetchone()
    if row:
        return "withdrawn" if row["dirty"] or row["status"]=="UNKNOWN" else "active"
    # History is an append-only receipt. Use JSON equality, not a substring in a quoted source.
    row=db.execute("""SELECT topic,kind FROM study3_log WHERE json_extract(receipt,'$.event.proof')=?
                      ORDER BY seq DESC LIMIT 1""",(pin,)).fetchone()
    if not row:return "unavailable"
    if row["kind"] in {"transfer","independent_test","review"} and row["topic"].startswith("card:"):
        card=db.execute("SELECT level,blocked FROM study3_card WHERE id=?",(row["topic"][5:],)).fetchone()
        return "active" if card and card["level"]>=3 and not card["blocked"] else "superseded"
    result=db.execute("SELECT status,dirty FROM study3_judgment WHERE claim=?",(row["topic"],)).fetchone()
    return "withdrawn" if result and (result["status"]=="UNKNOWN" or result["dirty"]) else "superseded"

def command(db,text):
    key=text.strip()
    if key in {"课程","课本","学情","学习进度"}:
        stats=db.execute("SELECT level,count(*) AS count FROM study3_card GROUP BY level ORDER BY level").fetchall()
        count=sum(r["count"] for r in stats)
        names="，".join(STAGES[r["level"]]+str(r["count"]) for r in stats)
        latest=db.execute("SELECT topic,receipt FROM study3_log ORDER BY seq DESC LIMIT 1").fetchone()
        last=json.loads(latest["receipt"])["event"]["summary"] if latest else "尚未开始。"
        return f"课本有 {count} 项。{names}。\n具有配套测验的条目支持本地复核。开放题保留给推理和人工评阅。\n最近一步：{last}\n可输入「学习卡 C-01」「学习目录」「学习来源」「学习命题 主张」。"
    if key=="学习目录":
        rows=db.execute("SELECT id,title,level FROM study3_card WHERE kind IN('文献批注','用户学习卡') ORDER BY id LIMIT 32")
        return "\n".join(f"{r['id']}  {r['title']} · {STAGES[r['level']]}" for r in rows)
    if key.startswith("学习卡 "):
        card=db.execute("SELECT * FROM study3_card WHERE id=?",(key[4:].strip().upper(),)).fetchone()
        if not card:return "没有这个学习卡编号。"
        return (f"{card['id']}  {card['title']} · {STAGES[card['level']]}\n{card['body']}\n边界：{card['boundary']}\n"
                f"来源：{card['source']}#{card['locator']}\n版本：{card['version']}")
    if key.startswith("导入学习卡 "):
        parts=[p.strip() for p in key[6:].split("|",2)]
        if len(parts)!=3 or not all(parts) or len(parts[0])>100 or len(parts[1])>340 or len(parts[2])>2000:
            return "用法：导入学习卡 标题 | 来源说明 | 摘要（最多 2000 字）。"
        title,origin,body=parts;ver=digest(packed(parts));ident="U-"+ver[:12].upper()
        db.execute("""INSERT OR IGNORE INTO study3_card(id,title,body,source,locator,version,kind,boundary)
                      VALUES(?,?,?,?,?,?,'用户学习卡','等待独立测验；仅限来源陈述。')""",(ident,title,body,origin,title,ver))
        return f"学习卡 {ident} 已登记为带来源的阅读材料。"
    if key in {"学习来源","捕捞来源","网络捕捞"}:
        feeds=db.execute("SELECT * FROM study3_feed ORDER BY rowid")
        rows=[f"{r['topic']} · {'启用' if r['enabled'] else '暂停'} · {r['detail'] or '待首次采集'}\n{r['url']}" for r in feeds]
        observed=db.execute("SELECT id,uri,active FROM study3_source ORDER BY seen DESC LIMIT 8")
        rows.extend(f"{r['id']} · {'有效' if r['active'] else '已撤回'} · {r['uri']}" for r in observed)
        return "\n".join(rows)
    if key.startswith(("订阅学习来源 ","暂停学习来源 ","恢复学习来源 ")):
        op,_,arg=key.partition(" ")
        try:url=public_url(arg.strip())
        except ValueError as e:return str(e)
        if op=="订阅学习来源":
            count=db.execute("SELECT count(*) FROM study3_feed").fetchone()[0]
            if count>=32 and not db.execute("SELECT 1 FROM study3_feed WHERE url=?",(url,)).fetchone():return "订阅已达到 32 项上限。"
            db.execute("INSERT OR IGNORE INTO study3_feed(url,topic) VALUES(?,?)",(url,parse.urlsplit(url).path))
        else:
            if not db.execute("UPDATE study3_feed SET enabled=? WHERE url=?",(int(op=="恢复学习来源"),url)).rowcount:return "没有此订阅。"
        return op+"已记录。"+url
    if key.startswith("学习证据 "):
        args=[v.strip() for v in key[5:].split("|",4)]
        if len(args)!=5 or args[1] not in {"支持","反对"} or not all(args) or max(map(len,args))>360:
            return "用法：学习证据 命题 | 支持或反对 | 原始来源族 | 版本 | 依据摘要。相同首发材料请使用相同的来源族。"
        claim,polarity,family,version,note=args
        sid=source_id(db,"教导:"+family,version,family);sgn=1 if polarity=="支持" else -1
        ident=observe(db,sid,claim,sgn,note,"用户提交 · "+digest(note)[:12],"testimony")
        return f"已登记来源 {sid}、观察 {ident}，等待核验。"
    if key.startswith("捕捞议题 "):
        term=key[5:].strip()
        if re.fullmatch(r"(?:HTTP\s*)?[1-5]\d\d",term,re.I):
            loc="Value="+term[-3:]
        elif re.fullmatch(r"[A-Za-z-]{2,16}",term):
            loc="Method="+term.upper()
        else:return "目前可按 HTTP 状态码或方法名从已读的公共登记表选题，例如「捕捞议题 202」。"
        r=explore(db,loc)
        if r:return r["summary"]
        existing=db.execute("""SELECT i.claim FROM study3_index i JOIN study3_source s ON s.id=i.source_id
                               WHERE s.active=1 AND i.locator=?""",(loc,)).fetchone()
        return "本项已进入学习队列："+existing[0] if existing else "当前已采登记表中没有对应条目。"
    if key.startswith("撤回学习来源 "):
        ident=key[7:].strip()
        row=db.execute("SELECT * FROM study3_source WHERE id=?",(ident,)).fetchone()
        if not row:return "没有这个来源版本编号。可用「学习来源」查看。"
        if not row["active"]:return "这一来源版本已经撤回。"
        invalidate(db,ident)
        event(db,"withdraw","source:"+ident,"撤回该来源版本，相关判断进入重算。",row["uri"]+" @"+row["version"],
              retracted=True,affected=[r[0] for r in db.execute("SELECT DISTINCT claim FROM study3_observation WHERE source_id=?",(ident,))])
        return "已撤回该来源版本。其依赖结论已标为待重算，其他来源仍保留。"
    if key.startswith("学习命题 "):
        claim=key[5:].strip()
        row=db.execute("SELECT * FROM study3_judgment WHERE claim=?",(claim,)).fetchone()
        if not row:return "UNKNOWN。尚无经过审核的来源。"
        if row["dirty"]:return "当前证据有变，结论待重算。"
        origins=json.loads(row["origins"])
        return f"{claim}\n来源支持状态 {row['status']}，独立迁移{'已通过' if row['mastered'] else '尚未通过'}。\n"+"；".join(
            x["source_id"]+" "+x["location"]+" @"+x["version"] for x in origins)+"\n证明摘要 "+row["proof"]
    if key.startswith("学习应用 "):
        parts=key[5:].split("|",1)
        if len(parts)!=2:return "用法：学习应用 C-01 | 英文特征1,英文特征2。用「学习规则 C-01」查看已归纳特征。"
        code=parts[0].strip().upper();features=list(dict.fromkeys(x.strip() for x in parts[1].split(",") if x.strip()))
        card=db.execute("SELECT * FROM study3_card WHERE id=?",(code,)).fetchone()
        if not card or not card["candidate"] or card["level"]<3:return "这张卡还没有通过独立检查的操作定义。"
        if len(features)>12 or not all(ID.fullmatch(x) for x in features):return "特征应为字母数字和下划线，共不超过 12 项。"
        _,proof=examine(db,json.loads(card["candidate"]),[dict(id="query",features=features,expected="UNKNOWN",context="用户查询的新情况")])
        return asset("operational_examples.json")[code]["term"]+"："+proof["actual"][0]+"。\n证明摘要 "+proof["proof_sha256"]
    if key.startswith("学习规则 "):
        code=key[5:].strip().upper()
        row=db.execute("SELECT candidate,level FROM study3_card WHERE id=?",(code,)).fetchone()
        if not row or not row["candidate"] or row["level"]<3:return "此卡还没有已通过独立检查的限定规则。"
        pos,neg=json.loads(row["candidate"])
        return asset("operational_examples.json")[code]["term"]+"\n支持条件："+", ".join(pos)+"\n反对条件："+", ".join(neg)
    return None

