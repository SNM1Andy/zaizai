import json,os,subprocess,sys,time,statistics
from pathlib import Path
HOME=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HOME/"host"))
import native as n
def main():
    evidence=HOME/"evidence"
    keys="".join(f"& fact{i} sample(g{i%10},n{i},{i%7}@cny_cent).\n" for i in range(2112))
    path=evidence/"projection-workload.cl"
    path.write_bytes((": sample(sym,sym,qty(cny_cent)).\n"+keys+": target(sym).\n"+
        "target($x) <- sample(g0,$x,0@cny_cent).\n? target(n0).\n? target(n70).\n").encode())
    data={}
    for label in ("cpu","gpu"):
        env=dict(os.environ,ZAIZAI_GPU_TRACE="1")
        if label=="cpu":env["ZAIZAI_CPU_ONLY"]="1"
        else:env.pop("ZAIZAI_CPU_ONLY",None)
        durations=[];traces=[]
        for i in range(3):
            start=time.perf_counter()
            p=subprocess.run([n.CL,"json",path],env=env,capture_output=True,check=True,timeout=45)
            durations.append(1000*(time.perf_counter()-start));traces.extend(p.stderr.decode().splitlines())
        data[label]={"ms":durations,"median_ms":statistics.median(durations),"inputs_per_s":2112/(statistics.median(durations)/1000),
                     "proof_sha256":n.sha(p.stdout),"kernel_trace":traces}
    data["device"]=subprocess.check_output(["nvidia-smi","--query-gpu=name,memory.total,driver_version","--format=csv,noheader"],text=True).strip()
    data["match"]=data["cpu"]["proof_sha256"]==data["gpu"]["proof_sha256"]
    ref=json.loads((n.LEX/"proof.json").read_bytes())
    actual=json.loads(n.run(n.CL,"package-prove",n.LEX/"lexicon_core.clpkg",n.LEX_PIN,n.LEX/"goals.txt"))
    data["linux_lexicon_proof_equal"]=ref==actual
    data["linux_lexicon_goals"]=len(actual["results"])
    (evidence/"compute.json").write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf8")
    print(data["match"], data["linux_lexicon_proof_equal"],len(data["gpu"]["kernel_trace"]),data["cpu"]["median_ms"],data["gpu"]["median_ms"])
    assert data["match"] and any(x.startswith("cuda_rows=") for x in data["gpu"]["kernel_trace"]) and data["linux_lexicon_proof_equal"]
if __name__=="__main__":main()

