"""Verify the two public DeepSeek/CL lexical releases from the public release ZIP. Python 3.10+, no third-party modules."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from zipfile import ZipFile

def sha(b):return hashlib.sha256(b).hexdigest()
def canonical(row):return (json.dumps(row,sort_keys=True,ensure_ascii=False,separators=(",",":"))+"\n").encode()
def verify(archive,expected,output=None):
    if expected:
        with archive.open("rb") as fp:
            chk=hashlib.sha256()
            while block:=fp.read(1024*1024):chk.update(block)
        if chk.hexdigest()!=expected.lower():raise ValueError("archive SHA-256 mismatch")
    out=None
    try:
        with ZipFile(archive) as z:
            paths=z.namelist()
            if len(paths)!=len(set(paths)) or any(x.startswith("/") or "\\" in x or ".." in x.split("/") for x in paths):raise ValueError("invalid member names")
            manifest=json.loads(z.read("MANIFEST.json"))
            if set(paths)!=(set(manifest["files"])|{"MANIFEST.json"}):raise ValueError("member set mismatch")
            for n,record in manifest["files"].items():
                raw=z.read(n)
                if len(raw)!=record["bytes"] or sha(raw)!=record["sha256"]:raise ValueError(n+" digest mismatch")
            rel=json.loads(z.read("releases.json"));meta=rel["r002"];delta=z.read(meta["changes"])
            if sha(delta)!=meta["changes_sha256"]:raise ValueError("delta checksum")
            change={r["sense_id"]:r for r in map(json.loads,delta.splitlines())}
            if len(change)!=meta["changes_count"]:raise ValueError("delta count")
            if output:out=output.open("xb")
            old=hashlib.sha256();new=hashlib.sha256();seen=set();applied=0
            for part in rel["r001"]["shards"]:
                raw=z.read(part["file"])
                if len(raw.splitlines())!=part["rows"] or sha(raw)!=part["sha256"]:raise ValueError("R001 shard")
                old.update(raw)
                for row in map(json.loads,raw.splitlines()):
                    sid=row["sense_id"]
                    if not re.fullmatch(r"LX-[0-9]{6}",sid) or sid in seen:raise ValueError("duplicate or malformed ID")
                    seen.add(sid)
                    if sid in change:
                        item=change[sid]
                        if item["previous_source_sha256"]!=row["upstream_sense_sha256"] or item["record"]["sense_id"]!=sid:raise ValueError("R002 preimage mismatch")
                        row=item["record"];applied+=1
                    wire=canonical(row);new.update(wire)
                    if out:out.write(wire)
            if len(seen)!=rel["records_per_release"] or applied!=meta["changes_count"]:raise ValueError("record counts mismatch")
            if old.hexdigest()!=rel["r001"]["public_stream_sha256"] or new.hexdigest()!=meta["public_stream_sha256"]:raise ValueError("release checksum")
        return {"verified":True,"records_per_release":len(seen),"replacements":applied,"r001":old.hexdigest(),"r002":new.hexdigest()}
    except BaseException:
        if out:out.close();output.unlink()
        raise
    finally:
        if out and not out.closed:out.close()
if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("archive",type=Path);p.add_argument("--sha256");p.add_argument("--write-r002",type=Path)
    a=p.parse_args();print(json.dumps(verify(a.archive,a.sha256,a.write_r002),indent=2))
