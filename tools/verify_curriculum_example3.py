"""A separate Windows CL check of the discrete-count criterion in the curriculum's first lesson."""
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile
import argparse,hashlib,json,subprocess
def evaluate(root,archive,out):
    chapter="zaizai_curriculum/01_数理与形式逻辑/G1.md"
    with ZipFile(archive) as z:
        raw=z.read(chapter)
    assert "M01-G1-01｜100以内加减与数量守恒" in raw.decode()
    rules=""": discrete(sym).
: before_count(sym,i64).
: after_count(sym,i64).
: retained(sym).
retained($x) <- discrete($x) & before_count($x,$v) & after_count($x,$v).
!retained($x) <- discrete($x) & before_count($x,$a) & after_count($x,$b) & int_lt($a,$b).
!retained($x) <- discrete($x) & before_count($x,$a) & after_count($x,$b) & int_lt($b,$a).
"""
    # Counts and objects below were newly specified for this test.
    observations="""& ribbon discrete(spools).
& initial before_count(spools,31).
& final after_count(spools,31).
& tiles discrete(tiles).
& before_tiles before_count(tiles,18).
& observed_lower after_count(tiles,16).
& jars discrete(jars).
& initial_jars before_count(jars,27).
& pieces discrete(pieces).
& initial_pieces before_count(pieces,14).
& first_source after_count(pieces,14).
& second_source after_count(pieces,15).
"""
    goals="\n".join("? retained("+x+")." for x in ("spools","tiles","jars","pieces"))+"\n"
    outcomes=[]
    with TemporaryDirectory() as tmp:
        path=Path(tmp)/"discrete.cl"
        for label,facts in [("independent_cases",observations),("withdraw_second_source",observations.replace("& second_source after_count(pieces,15).\n",""))]:
            path.write_bytes((rules+facts+goals).encode())
            p=subprocess.run([root/"bin/cl.exe","json",path],capture_output=True,check=True,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
            data=json.loads(p.stdout)
            s={x["goal"]["arguments"][0]["value"]:x["status"] for x in data["results"]}
            assert s=={"spools":"POSITIVE","tiles":"NEGATIVE","jars":"UNKNOWN","pieces":"CONFLICT" if label=="independent_cases" else "POSITIVE"}
            outcomes.append({"case":label,"status":s,"program_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"proof":data})
    payload={"lesson":"M01-G1-01","criterion":"前后两次计数有来源、均针对同一离散对象时判断数量是否保持",
             "chapter_sha256":hashlib.sha256(raw).hexdigest(),"cl_sha256":hashlib.sha256((root/"bin/cl.exe").read_bytes()).hexdigest(),
             "assessment":"规则兼容性探针，不授予课程掌握分","runs":outcomes}
    out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf8"); print(outcomes[0]["status"],outcomes[1]["status"]["pieces"])
if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("archive",type=Path);parser.add_argument("output",type=Path)
    parser.add_argument("--root",type=Path,default=Path("D:/再再2.0"))
    args=parser.parse_args();evaluate(args.root,args.archive,args.output)
