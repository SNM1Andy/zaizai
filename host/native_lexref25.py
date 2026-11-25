"""Explicit lexical-reference operations on native PCGM. Lexical descriptions are always data."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import zlib

BASE="1372d858218edbf23a195e42caa9632c181a05ff7546dc6950d1d6a16fc3918b"
CURRENT="8d9ce0772bad5beaa9b9e01e217477bb54299536814a15d4f922c7a724a335ba"
INDEX="804c708ee9f773e6664df734064c6666818f24b13649d9a0d906d37f1bae05f7"
MODULE=Path(__file__).resolve().with_name("lexref25.cl")
MODULE_PIN="314b967e416d00e1178f003e0447008c7bd387212b365d26ce9a6ae21a1a3504"
NAME="lexref25"

def need(ok,reason):
    if not ok:raise ValueError(reason)
def sha(data):return hashlib.sha256(data).hexdigest()
def split(pin):
    need(re.fullmatch(r"[0-9a-f]{64}",pin),"invalid exact SHA-256")
    return "h"+pin[:32],"h"+pin[32:]
def unsplit(a,b):
    need(all(re.fullmatch(r"h[0-9a-f]{32}",x) for x in (a,b)),"native hash fragments differ")
    return a[1:]+b[1:]
def record_key(name):
    need(re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,15}",name),"record ID must be 1–16 ASCII characters")
    return "r"+name.encode().hex()
def symbol(sid):
    if re.fullmatch(r"LX-\d{6}",sid):return "lx_"+sid[3:]
    if re.fullmatch(r"TST-LEX-\d{4}",sid):return "tst_"+sid[-4:]
    raise ValueError("invalid sense ID")
def atom(name,*values):return name+"("+",".join(values)+")"
def label(prefix,*values):return "xr"+prefix+sha(("\0".join(values)).encode())[:17]
def invoke(exe,args,body=b""):
    p=subprocess.run([exe,*args],input=body,capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
    if p.returncode:raise ValueError((p.stderr or p.stdout).decode("utf8","replace")[:400])
    return p.stdout.decode("utf8")

class Journal:
    releases=(BASE,CURRENT)
    def __init__(self,root,bins,actor):
        self.root=Path(root).resolve(strict=True)
        self.state=self.root/"state/individual.pcgm"
        self.bins=Path(bins).resolve(strict=True)
        self.probe=self.bins/"pcgm-alpha.exe"
        self.actor=actor
        need(sha(MODULE.read_bytes())==MODULE_PIN,"lexical module does not match the approved source")
    def snap(self):
        r=json.loads(invoke(self.probe,["--desktop-snapshot",self.state]))
        need(r.get("individual")==self.actor and r.get("owner") in ("alpha","beta"),"identity/owner mismatch")
        return r
    def writer(self,snap,command):
        out=invoke(self.bins/("pcgm-"+snap["owner"]+".exe"),["--resume",self.state],(command+"\n").encode()).splitlines()
        need(out and out[0].startswith("individual="+self.actor+" "),"unexpected write target")
        need(not any(s.startswith("QUERY_ERROR") for s in out),"native request refused: "+" ".join(out[1:])[:350])
        return out[1:]
    def read(self,query):
        raw=json.loads(invoke(self.probe,["--read-channel",self.state],("lexref "+query+"\n").encode()))
        need(raw.get("id")=="lexref" and raw.get("ok"),"native read refused: "+str(raw.get("error","")))
        return raw["payload"]
    def verify_source(self,snap):
        delimiter="# module "+NAME+"\n"
        before,sep,after=snap["source"].partition(delimiter)
        need(sep and after.startswith(MODULE.read_text(encoding="utf8")),"native module missing or not from this release")
        outside=before+"\n"+after[len(MODULE.read_text(encoding="utf8")):]
        for line in outside.splitlines():
            if "lexref25_" in line:
                need(re.fullmatch(r"& xr[a-z][0-9a-f]{17} lexref25_(?:chosen|binding|version|available|retired|tombstone_at)\([a-z0-9_,]+\)\.",line),"foreign statements in lexical namespace")
    def install(self,expected_head):
        s=self.snap()
        if "# module "+NAME+"\n" in s["source"]:
            self.verify_source(s);return {"outcome":"already_installed","module_sha256":MODULE_PIN,"head":s["head"]}
        need(s["head"]==expected_head and "lexref25_" not in s["source"],"stale head or namespace occupied")
        dest=self.state.parent/"modules"/(NAME+".cl")
        need(dest.parent.is_dir() and dest.parent.resolve()==dest.parent and dest.resolve()==dest,"invalid module path")
        if dest.exists():need(sha(dest.read_bytes())==MODULE_PIN,"existing module differs")
        else:
            with tempfile.NamedTemporaryFile(dir=dest.parent,delete=False) as f:
                tmp=Path(f.name);f.write(MODULE.read_bytes());f.flush();os.fsync(f.fileno())
            try:os.rename(tmp,dest)
            finally:tmp.unlink(missing_ok=True)
        out=self.writer(s,":install "+NAME);s=self.snap();self.verify_source(s)
        need(any(x.endswith("module_installed "+NAME) for x in out),"missing native installation receipt")
        return {"outcome":"installed","module_sha256":MODULE_PIN,"head":s["head"],"receipt":out}
    def records(self,s):
        self.verify_source(s);inactive=set(s["inactive"]);rows={}
        for ob,pred,args in re.findall(r"(?m)^& (xr[a-z][0-9a-f]{17}) (lexref25_\w+)\(([a-z0-9_,]+)\)\.$",s["source"]):
            need(ob not in rows,"duplicate native observation")
            rows[ob]=(pred,args.split(","),ob not in inactive)
        return rows
    def batch(self,s,phase,semantics,edits,expected_head):
        need(expected_head==s["head"],"stale native head; no new effect")
        key=label("b",phase,semantics,expected_head)
        wire=":observation_batch "+key+" "+expected_head+" ; "+" ; ".join(edits)
        need(len(wire.encode())<=511,"native frame exceeds 511 bytes")
        result=self.writer(s,wire);need(len(result)==1,"unexpected batch response")
        committed=json.loads(result[0]);wire_pin=sha(wire.encode())
        stored=self.read("observation_batch "+key+" "+wire_pin)
        need(stored["basis_sha256"]==expected_head and stored["event"]==committed["event"],"native batch readback mismatch")
        return {"request_pin":wire_pin,"batch":key,"basis":expected_head,"head":self.snap()["head"],"event":committed["event"],"native_receipt":stored}
    @staticmethod
    def selected(rows):
        picks=[unsplit(*values) for pred,values,active in rows.values() if pred=="lexref25_chosen" and active]
        need(len(picks)<=1,"ambiguous native lexical release")
        return picks[0] if picks else None
    def select(self,release,head):
        need(release in self.releases,"not a known, fingerprinted release")
        s=self.snap();rows=self.records(s);old=self.selected(rows);tag=label("v",release)
        if old==release:return {"outcome":"already_selected","release":release,"head":s["head"]}
        changes=["withdraw "+label("v",old)] if old else []
        changes.append("restore "+tag if tag in rows else "observe "+tag+" "+atom("lexref25_chosen",*split(release)))
        receipt=self.batch(s,"select",release,changes,head)
        need(self.selected(self.records(self.snap()))==release,"wrong release after native commit")
        return {"release":release,"receipt":receipt}
    def binding(self,rows,name):
        rec=record_key(name);b=rows.get(label("b",rec));v=rows.get(label("r",rec))
        if not b and not v:return None
        need(b and v and b[0]=="lexref25_binding" and v[0]=="lexref25_version" and b[2] and v[2] and b[1][0]==v[1][0]==rec,"incomplete or inactive immutable lexical binding")
        term=b[1][1]
        if re.fullmatch(r"lx_\d{6}",term):sid="LX-"+term[3:]
        elif re.fullmatch(r"tst_\d{4}",term):sid="TST-LEX-"+term[4:]
        else:raise ValueError("unknown lexical sense encoding")
        return sid,unsplit(*b[1][2:]),unsplit(*v[1][1:])
    def bind_pins(self,name,sid,content_pin,release,head):
        s=self.snap();rows=self.records(s);rec=record_key(name);bound=self.binding(rows,name)
        if bound:
            need(bound==(sid,content_pin,release),"record ID already binds different content or release")
            return {"outcome":"already_bound","record":name,"head":s["head"]}
        need(self.selected(rows)==release,"requested lexical release is not current")
        need(label("t",sid,release) not in rows and label("d",sid,release) not in rows,"tombstoned release/sense cannot be rebound")
        args=(symbol(sid),*split(release));available=label("a",sid,release)
        edits=["observe "+label("b",rec)+" "+atom("lexref25_binding",rec,symbol(sid),*split(content_pin)),
               "observe "+label("r",rec)+" "+atom("lexref25_version",rec,*split(release))]
        if available not in rows:edits.append("observe "+available+" "+atom("lexref25_available",*args))
        else:need(rows[available]==("lexref25_available",list(args),True),"availability receipt is inconsistent")
        result=self.batch(s,"bind",name+content_pin,edits,head)
        need(self.binding(self.records(self.snap()),name)==(sid,content_pin,release),"read-back pinned addresses differ")
        return result
    def retire(self,name,head):
        s=self.snap();rows=self.records(s);match=self.binding(rows,name)
        need(match,"no such lexical record")
        sid,pin,release=match;tag=label("t",sid,release);available=label("a",sid,release)
        if tag in rows:
            need(rows[tag][2] and not rows[available][2],"inconsistent tombstone")
            return {"outcome":"already_tombstoned","head":s["head"],"record":name}
        need(available in rows and rows[available][2],"missing active availability observation")
        at=self.selected(rows);need(at,"no release selected")
        edits=["withdraw "+available,"observe "+tag+" "+atom("lexref25_retired",symbol(sid),*split(release))]
        publication=label("d",sid,at)
        if publication not in rows:edits.append("observe "+publication+" "+atom("lexref25_tombstone_at",symbol(sid),*split(at)))
        return self.batch(s,"retire",sid+release+at,edits,head)
    def prove(self,a):
        r=self.read("proof "+a)
        need(len(r["results"])==1,"proof count differs")
        return r["results"][0]
    def receipt(self,name):
        s=self.snap();rows=self.records(s);match=self.binding(rows,name);need(match,"no such lexical record")
        sid,content_pin,release=match;ref=record_key(name)
        bb=self.prove(atom("lexref25_binding",ref,symbol(sid),*split(content_pin)))
        vv=self.prove(atom("lexref25_version",ref,*split(release)))
        live=self.prove(atom("lexref25_active",ref));dead=self.prove(atom("lexref25_tombstone",ref))
        statuses=(live["status"],dead["status"])
        need(bb["status"]==vv["status"]=="POSITIVE" and statuses in (("POSITIVE","UNKNOWN"),("POSITIVE","POSITIVE"),("UNKNOWN","POSITIVE")),"native reference state is inconsistent")
        return {"record":name,"sense_id":sid,"release_sha256":release,"sense_digest":content_pin,
                "native_head":s["head"],"identity":s["individual"],"tombstone":dead["status"]=="POSITIVE",
                "proofs":{"binding":bb,"written_version":vv,"available":live,"tombstone":dead},
                "lexical_reference_only":True}
    def read_binding(self,name,catalog,resolve=None):
        result=self.receipt(name)
        item=(resolve or lookup)(catalog,result["sense_id"],result["release_sha256"])
        need(item["digest"]==result["sense_digest"],"native value differs from supplied versioned content")
        withheld=item["holdout"] or item.get("side","importable")!="importable"
        return dict(result,content_withheld=withheld,content=None if withheld else item["content"])

def lookup(catalog,sid,release):
    """Resolve exact content bytes; callers separately decide whether a new reference is permissible."""
    need(re.fullmatch(r"LX-\d{6}",sid) and release in (BASE,CURRENT),"unknown production release or sense")
    path=Path(catalog).resolve(strict=True)
    with closing(sqlite3.connect(path.as_uri()+"?mode=ro&immutable=1",uri=True)) as d:
        row=d.execute("select side,digest,previous,record from sense where id=?",(sid,)).fetchone()
        need(row,"sense not found")
        digest=(row[2] or row[1]) if release==BASE else row[1]
        hit=d.execute("select content from revision where id=? and digest=?",(sid,digest)).fetchone()
        need(hit,"pinned revision content missing")
        body=zlib.decompress(hit[0]);need(sha(body)==digest,"stored lexical bytes changed")
        info=json.loads(zlib.decompress(row[3]))
        return {"side":row[0],"digest":digest,"holdout":bool(info["checks"]["holdout"]),"content":json.loads(body)}

def main():
    p=argparse.ArgumentParser(description="在当前个体仅登记明确请求的词典版本引用")
    p.add_argument("--root",required=True,type=Path);p.add_argument("--bin",type=Path);p.add_argument("--catalog",type=Path)
    p.add_argument("--identity",required=True);p.add_argument("--head");p.add_argument("--apply",action="store_true")
    p.add_argument("op",choices=("status","install","set-release","bind","receipt","read","tombstone"));p.add_argument("args",nargs="*")
    options=p.parse_args();root=options.root.resolve(strict=True)
    sys.path.insert(0,str(root/"host"));import service as host
    journal=Journal(root,options.bin or root/"releases/joint25/bin",options.identity)
    catalog=options.catalog or root/"learning_materials/release25-lexicon/lexicon-r002.sqlite"
    with host.writer():
        # Validate the actual register before either reading from or writing to the selected provider.
        with closing(host.store()) as d:
            import slots31
            binding=slots31.snapshot(d)["C"]
            need(binding["id"]=="joint25-pcgm" and binding["state"]=="ready","joint native C must be active and ready")
        op=options.op;args=options.args;expected={"status":0,"install":0,"set-release":1,"bind":3,"receipt":1,"read":1,"tombstone":1}
        need(len(args)==expected[op],"incorrect argument count")
        if op not in ("receipt","read","status"):need(options.apply and re.fullmatch(r"[0-9a-f]{64}",options.head or ""),"supply the reviewed --head and --apply")
        if op in ("read","bind"):
            with Path(catalog).open("rb") as stream:need(hashlib.file_digest(stream,"sha256").hexdigest()==INDEX,"unexpected catalogue artifact")
        s=journal.snap()
        if op=="status":result={"identity":s["individual"],"head":s["head"],"registered":("# module "+NAME+"\n") in s["source"]}
        elif op=="install":result=journal.install(options.head)
        elif op=="set-release":result=journal.select(args[0],options.head)
        elif op=="receipt":result=journal.receipt(args[0])
        elif op=="read":result=journal.read_binding(args[0],catalog)
        elif op=="tombstone":result=journal.retire(args[0],options.head)
        else:
            name,sid,digest=args;release=journal.selected(journal.records(s))
            item=lookup(catalog,sid,release)
            need(item["side"]=="importable" and not item["holdout"] and item["digest"]==digest,"not an exact approved candidate-reference address")
            # Native refs also honor the live governance view. This never reactivates a pending/withdrawn sense.
            import release25_lexicon as lex
            with closing(host.store()) as db:
                checked=lex.resolve(sid,digest,release_sha256=release,db=db,catalog_path=catalog)
                need(checked["state"]=="importable" and not checked["content_withheld"],"host governance view excludes this address")
            result=journal.bind_pins(name,sid,digest,release,options.head)
        print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
