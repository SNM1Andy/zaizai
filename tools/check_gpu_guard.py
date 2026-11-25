from pathlib import Path
import sys,os,subprocess,json
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"host"))
import native as n
p=ROOT/"evidence/projection-workload.cl"
def sample(env):
    cmd=[n.CL,"json",p]
    r=subprocess.run(cmd,check=True,capture_output=True,env=dict(os.environ,ZAIZAI_GPU_TRACE="1",**env))
    return n.sha(r.stdout),r.stderr.decode().splitlines()
normal,trace=sample({})
cpu,_=sample({"ZAIZAI_CPU_ONLY":"1"})
fallback,reason=sample({"ZAIZAI_GPU_MIN_FREE_MIB":"99999"})
assert normal==cpu==fallback and "cuda_fallback=vram_reserve" in reason and not any(x.startswith("cuda_rows=") for x in reason)
report=dict(reserve_mib=3072,stop_at_c=87,load_target_percent=99,normal=trace,forced_memory_limit=reason,
            cpu_semantics_identical=True,whole_gpu_readback=subprocess.check_output(["nvidia-smi",
            "--query-gpu=memory.free,temperature.gpu,utilization.gpu","--format=csv,noheader"],text=True).strip())
(ROOT/"evidence/gpu-policy.json").write_text(n.canonical(report),encoding="utf8")
print(report)

