"""Read the frozen DeepSeek release as lexical suggestions, preserving governance and revision pins."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
import zlib

RELEASE="CL-LEX-R002-DELIVER-20261125"
RELEASE_PIN="8d9ce0772bad5beaa9b9e01e217477bb54299536814a15d4f922c7a724a335ba"
BASE_PIN="1372d858218edbf23a195e42caa9632c181a05ff7546dc6950d1d6a16fc3918b"
INDEX_PIN="804c708ee9f773e6664df734064c6666818f24b13649d9a0d906d37f1bae05f7"
INDEX_SIZE=335609856
ROOT=Path(__file__).resolve().parents[1]
CATALOG=ROOT/"learning_materials/release25-lexicon/lexicon-r002.sqlite"
SENSE=re.compile(r"LX-[0-9]{6}\Z")
BATCH=re.compile(r"G(?:0[1-9]|1[0-9]|20)\Z")
PIN=re.compile(r"[0-9a-f]{64}\Z")

def require(test,message):
    if not test:raise ValueError(message)
def unpack(data):return json.loads(zlib.decompress(data))
def _connect(path=None):
    p=Path(path or CATALOG).resolve(strict=True)
    if p.stat().st_size!=INDEX_SIZE:raise ValueError("候选词库文件长度与已验收版本不符")
    db=sqlite3.connect(p.as_uri()+"?mode=ro&immutable=1",uri=True)
    db.row_factory=sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    try:
        row=db.execute("SELECT value FROM metadata WHERE key='release_sha256'").fetchone()
        require(row and json.loads(row[0])==RELEASE_PIN,"词库发布版本不符")
    except BaseException:
        db.close(); raise
    return db

def verify_index(catalog_path=None):
    path=Path(catalog_path or CATALOG).resolve(strict=True)
    with path.open("rb") as f:pin=hashlib.file_digest(f,"sha256").hexdigest()
    require(pin==INDEX_PIN,"候选词库文件摘要与正式交接不符")
    with closing(_connect(path)) as db:
        return {"index_sha256":pin,**{k:json.loads(v) for k,v in db.execute("SELECT key,value FROM metadata")}}

def setup(db):
    """The overlay is part of the host backup; attaching the read-only catalogue has no side effects."""
    db.execute("""CREATE TABLE IF NOT EXISTS lex25_changes(
        seq INTEGER PRIMARY KEY, request TEXT UNIQUE NOT NULL, release_pin TEXT NOT NULL, selector TEXT NOT NULL,
        target TEXT NOT NULL, enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), reason TEXT NOT NULL,stamp_ns INTEGER NOT NULL)""")
    db.execute("CREATE INDEX IF NOT EXISTS lex25_scope ON lex25_changes(release_pin,selector,target,seq DESC)")
    for op in ("UPDATE","DELETE"):
        db.execute(f"CREATE TRIGGER IF NOT EXISTS lex25_immutable_{op.lower()} BEFORE {op} ON lex25_changes BEGIN SELECT RAISE(ABORT,'append a lexical revision'); END")
    db.execute("""CREATE TABLE IF NOT EXISTS lex25_receipt(
        request TEXT PRIMARY KEY, session TEXT NOT NULL, release_pin TEXT NOT NULL, id TEXT NOT NULL,
        digest TEXT NOT NULL, view INTEGER NOT NULL, created_ns INTEGER NOT NULL)""")
    for op in ("UPDATE","DELETE"):
        db.execute(f"CREATE TRIGGER IF NOT EXISTS lex25_receipt_{op.lower()} BEFORE {op} ON lex25_receipt BEGIN SELECT RAISE(ABORT,'immutable lexical reference'); END")
def _has(db):
    return db is not None and bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lex25_changes'").fetchone())
def _view(db,as_of):
    if as_of is not None and (type(as_of) is not int or as_of<0):raise ValueError("无效词库视图序号")
    last=db.execute("SELECT coalesce(max(seq),0) FROM lex25_changes WHERE release_pin=?",(RELEASE_PIN,)).fetchone()[0] if _has(db) else 0
    if as_of is not None and as_of>last:raise ValueError("词库视图不存在")
    return last if as_of is None else as_of
def _enabled(db,side,key,view):
    if not view:return True
    rec=db.execute("SELECT enabled FROM lex25_changes WHERE release_pin=? AND selector=? AND target=? AND seq<=? ORDER BY seq DESC LIMIT 1",
                   (RELEASE_PIN,side,key,view)).fetchone()
    return rec is None or bool(rec[0])
def change_view(db,selector,target,enabled,reason,request,*,catalog_path=None):
    """Administrative tombstone or restoration. The caller owns the host write transaction."""
    require(isinstance(reason,str) and 0<len(reason.strip())<=300,"需要变更原因（最多 300 字）")
    require(isinstance(request,str) and 0<len(request)<=120,"需要稳定请求号")
    require(type(enabled) is bool,"状态须为布尔值")
    require((selector=="sense" and SENSE.fullmatch(target)) or (selector=="batch" and BATCH.fullmatch(target)),"请选择原义项 ID 或治理批次")
    with closing(_connect(catalog_path)) as c:
        row=c.execute("SELECT id FROM sense WHERE id=?",(target,)).fetchone() if selector=="sense" else c.execute(
            "SELECT id FROM sense WHERE group_id=? AND side='importable' LIMIT 1",(target,)).fetchone()
        require(row is not None,"未知义项或治理批次")
    setup(db);old=db.execute("SELECT seq,release_pin,selector,target,enabled,reason FROM lex25_changes WHERE request=?",(request,)).fetchone()
    payload=(RELEASE_PIN,selector,target,int(enabled),reason)
    if old:
        require(tuple(old)[1:]==payload,"同一请求携带不同的词库变更")
        return {"view":old[0],"repeat":True}
    cur=db.execute("INSERT INTO lex25_changes(request,release_pin,selector,target,enabled,reason,stamp_ns) VALUES(?,?,?,?,?,?,?)",
                   (request,*payload,time.time_ns()))
    return {"view":cur.lastrowid,"repeat":False}

def _result(c,control,word,view,include_pending,limit):
    current=pending=withdrawn=0;entries=[];witnesses=[]
    for row in c.execute("""SELECT s.id,s.side,s.group_id,s.record FROM label l JOIN sense s ON s.id=l.id WHERE l.label=? ORDER BY s.id""",(word,)):
        rec=unpack(row["record"]);allowed=_enabled(control,"batch",row["group_id"],view) and _enabled(control,"sense",row["id"],view)
        if row["side"]=="pending":
            pending+=1
            if include_pending and len(witnesses)<limit:
                # Preserve test-set blindness in every serving path, including review summaries.
                witnesses.append({"sense_id":rec["sense_id"],"sense_digest":rec["sense_digest"],"pending_reason":rec["pending_reason"],
                                  "release":RELEASE,"release_sha256":RELEASE_PIN,"state":"pending","content_withheld":True})
        elif not allowed:withdrawn+=1
        else:
            current+=1
            if len(entries)<limit:
                entries.append({k:rec[k] for k in ("sense_id","headword","gloss_zh","boundary","domain","source_refs",
                              "sense_digest","revision","quality","decision","status","predicate_signature","previous_revision")} |
                              {"release":RELEASE,"release_sha256":RELEASE_PIN,"view":view,"human_reviewed":False})
    return {"word":word,"release":RELEASE,"release_sha256":RELEASE_PIN,"view":view,"entries":entries,"candidate_count":current,
            "pending_count":pending,"withdrawn_count":withdrawn,"pending":witnesses,"truncated":current>limit,
            "ambiguity":"multiple_candidates" if current>1 or (current and pending) else "one_candidate" if current else "unresolved",
            "formal_meanings":[],"lexical_only":True}

def lookup(word,*,db=None,catalog_path=None,include_pending=False,limit=12,as_of=None):
    require(isinstance(word,str) and 0<len(word)<=128 and type(limit) is int and 1<=limit<=48,"词头或查询预算无效")
    view=_view(db,as_of)
    with closing(_connect(catalog_path)) as c:return _result(c,db,word,view,include_pending,limit)

def resolve(sense_id,sense_digest,*,release_sha256=RELEASE_PIN,db=None,catalog_path=None,as_of=None):
    """Resolve the exact historical record; a later tombstone is reported without reinterpreting the old bytes."""
    require(SENSE.fullmatch(sense_id) and PIN.fullmatch(sense_digest) and release_sha256 in (BASE_PIN,RELEASE_PIN),"义项地址或发行摘要无效")
    view=_view(db,as_of)
    with closing(_connect(catalog_path)) as c:
        row=c.execute("SELECT digest,previous,side,group_id,record FROM sense WHERE id=?",(sense_id,)).fetchone()
        require(row is not None and sense_digest==((row["previous"] or row["digest"]) if release_sha256==BASE_PIN else row["digest"]),"版本或义项不匹配")
        historical=c.execute("SELECT content FROM revision WHERE id=? AND digest=?",(sense_id,sense_digest)).fetchone()
        require(historical is not None,"找不到固定版本的内容")
        raw=zlib.decompress(historical[0]);require(hashlib.sha256(raw).hexdigest()==sense_digest,"义项原文校验失败")
        content=json.loads(raw);frozen=bool(unpack(row["record"])["checks"]["holdout"])
        return {"sense_id":sense_id,"sense_digest":sense_digest,"release_sha256":release_sha256,"view":view,
                "state":"tombstone" if not (_enabled(db,"sense",sense_id,view) and _enabled(db,"batch",row["group_id"],view)) else row["side"],
                "content":None if frozen else content,"content_withheld":frozen,"human_reviewed":False}

def bind_reference(db,request,session,sense_id,sense_digest,*,release_sha256=RELEASE_PIN,catalog_path=None):
    """Record a user-requested lexical reference. Neither a candidate nor an example becomes a fact."""
    require(isinstance(request,str) and 0<len(request)<=120 and isinstance(session,str) and 0<len(session)<=120,"需要会话与请求号")
    setup(db)
    old=db.execute("SELECT session,release_pin,id,digest,view FROM lex25_receipt WHERE request=?",(request,)).fetchone()
    key=(session,release_sha256,sense_id,sense_digest)
    if old:
        require(tuple(old[:4])==key,"同一请求携带不同的义项版本")
        return read_reference(db,request,session,catalog_path=catalog_path)
    record=resolve(sense_id,sense_digest,release_sha256=release_sha256,db=db,catalog_path=catalog_path)
    require(record["state"]=="importable" and not record["content_withheld"],"该义项版本尚待复核或已撤回")
    db.execute("INSERT INTO lex25_receipt VALUES(?,?,?,?,?,?,?)",(request,*key,record["view"],time.time_ns()))
    return read_reference(db,request,session,catalog_path=catalog_path)

def read_reference(db,request,session,*,catalog_path=None):
    row=db.execute("SELECT release_pin,id,digest,view FROM lex25_receipt WHERE request=? AND session=?",(request,session)).fetchone()
    require(row,"本会话没有该义项凭据")
    version,sid,pin,view=row
    historical=resolve(sid,pin,release_sha256=version,db=db,catalog_path=catalog_path,as_of=view)
    current=resolve(sid,pin,release_sha256=version,db=db,catalog_path=catalog_path)
    return {"request":request,"session":session,"original":historical,"current_view_state":current["state"],
            "formal_approval":False}
def mention(text,limit=5,*,db=None,catalog_path=None,as_of=None):
    """Enumerate unmodified UTF-8 spans. Longest exact non-overlapping candidate labels take precedence."""
    require(isinstance(text,str) and 0<len(text)<=512 and type(limit) is int and 1<=limit<=24,"分词证据单次接受 1–512 个字符、至多 24 个词头")
    view=_view(db,as_of);n=len(text);terms={}
    for start in range(n):
        if not text[start].isalnum():continue
        for end in range(start+1,min(n,start+19)+1):
            if not text[end-1].isalnum():break
            terms.setdefault(text[start:end],[]).append((start,end))
    if not terms:return []
    with closing(_connect(catalog_path)) as c:
        found=set();words=sorted(terms)
        for start in range(0,len(words),250):
            batch=words[start:start+250];sql="SELECT DISTINCT l.label FROM label l JOIN sense s ON s.id=l.id WHERE s.side='importable' AND l.label IN ("+",".join("?" for _ in batch)+")"
            found.update(r[0] for r in c.execute(sql,batch))
        positions=sorted(((i,j,word) for word in found for i,j in terms[word]),key=lambda x:(x[0]-x[1],x[0],x[2]))
        taken=set();spans=[];items={}
        offset=[0]
        for ch in text:offset.append(offset[-1]+len(ch.encode("utf8")))
        for i,j,word in positions:
            if any(k in taken for k in range(i,j)):continue
            info=items.get(word)
            if info is None:info=items[word]=_result(c,db,word,view,False,12)
            if not info["entries"]:continue
            spans.append(dict(info,byte_span=[offset[i],offset[j]]));taken.update(range(i,j))
        return sorted(spans,key=lambda x:x["byte_span"][0])[:limit]

def command(db,text,session=None,request=None,*,catalog_path=None):
    import corelex25
    technical=corelex25.command(text)
    if technical is not None:return technical
    q=text.strip().rstrip("。！？!?")
    if q in ("候选词典","候选词库"):
        with closing(_connect(catalog_path)) as c:m={k:json.loads(v) for k,v in c.execute("SELECT key,value FROM metadata")}
        return (f"{m['release']} · 候选资料 {m['total']:,} 条（{m['headwords']:,} 个词头）。可检索提案 {m['sides']['importable']:,} 条，"
                f"待复核 {m['sides']['pending']:,} 条，独立人工核准 {m['human_reviewed']} 条。输入「候选词义 词头」或「词义历史 LX-编号」。")
    if q.startswith(("候选词义 ","待复核词义 ")):
        op,word=q.split(" ",1);word=word.strip()
        result=lookup(word,db=db,catalog_path=catalog_path,include_pending=op=="待复核词义")
        lines=[f"「{word}」可用候选 {result['candidate_count']}，待复核 {result['pending_count']}，已撤回 {result['withdrawn_count']}。"]
        if op=="待复核词义":lines.extend(f"{r['sense_id']} · {r['pending_reason']} · {r['sense_digest'][:16]}" for r in result["pending"])
        else:lines.extend(f"{r['sense_id']} · {r['gloss_zh']} · 边界 {r['boundary']} · 来源 {' / '.join(r['source_refs'])} · {r['sense_digest'][:16]}" for r in result["entries"])
        lines.append(f"候选发行 {RELEASE} · 视图 {result['view']}。释义不能单独证明事实。")
        return "\n".join(lines)
    if q.startswith("词义历史 "):
        sid=q[5:].strip()
        require(SENSE.fullmatch(sid),"请给出 LX- 加六位数字")
        with closing(_connect(catalog_path)) as c:row=c.execute("SELECT digest,previous,side,head FROM sense WHERE id=?",(sid,)).fetchone()
        if not row:return "该发行版没有这个义项编号。"
        return f"{sid} · {row['head']} · {row['side']}\n当前版本 {row['digest']}\n基线版本 {row['previous'] or row['digest']}\n发行摘要 {RELEASE_PIN}"
    if q.startswith("引用候选义项 "):
        sid=q.partition(" ")[2].strip()
        require(db is not None and request and session and SENSE.fullmatch(sid),"请在有请求号的本机会话中给出 LX- 加六位数字")
        with closing(_connect(catalog_path)) as c:row=c.execute("SELECT digest FROM sense WHERE id=?",(sid,)).fetchone()
        require(row,"未找到指定候选义项")
        ref=bind_reference(db,request,session,sid,row[0],catalog_path=catalog_path)
        return f"词义凭据 {request}。{sid} · {ref['original']['sense_digest']}。本次仅引用候选。"
    if q.startswith("复查词义凭据 "):
        require(db is not None and session,"需要当前会话")
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lex25_receipt'").fetchone():return "本会话尚无词义凭据。"
        r=read_reference(db,q.partition(" ")[2].strip(),session,catalog_path=catalog_path);original=r["original"]
        return f"{original['sense_id']} · 原始版本 {original['sense_digest']}\n引用时：{original['content']['definition']}\n当前视图 {r['current_view_state']}。"
    return None

