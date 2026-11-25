from pathlib import Path
import json
import os
import subprocess
import build as b
out=b.OBJ/"acceptance"
out.mkdir(exist_ok=True)
exe=out/"policy-edges.exe"
b.run("policy-edges",b.common+[str(b.ROOT/"tools/check_policy_edges.cpp"),"/Fo"+str(out/"policy-edges.obj"),"/Fe"+str(exe)])
env=dict(os.environ)
env.pop("ZAIZAI_GPU_MIN_FREE_MIB",None)
r=subprocess.run([exe],capture_output=True,check=True,env=env)
(b.ROOT/"evidence/policy-edges.json").write_text(json.dumps({"source":"injected NVML samples through native Monitor::admit","exit":r.returncode,"result":r.stdout.decode().strip()},indent=2),encoding="utf8")
print(r.stdout.decode().strip())
