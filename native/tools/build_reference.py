"""Build the independent projection and concurrency references named in the delivered Makefile."""
from build import common,run,compiler,SRC,OBJ,ROOT
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
out=ROOT/"reference-bin";out.mkdir(exist_ok=True)
jobs={"cl-projection-direct":("cl-src/cl.cpp",["/DCL_DIRECT_PROJECTION"]),
      "cl-native-projection-direct":("cl-src/cl.cpp",["/DCL_DIRECT_PROJECTION","/DCL_NATIVE_LIBRARY"]),
      "pcgm-projection-direct":("pcgm-src/cl.cpp",["/DCL_DIRECT_PROJECTION",'/DPCGM_BUILD_NAME="alpha"']),
      "cl-projection-two-worker":("cl-src/cl.cpp",["/DCL_RANK_TWO_WORKER_REFERENCE"]),
      "projection-kernel-check":("projection-kernel-check.cpp",[])}
def compile_ref(name):
 source,flags=jobs[name];run(name,common+flags+["/c",str(SRC/source),"/Fo"+str(OBJ/(name+".obj"))])
with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(compile_ref,jobs))
for name in jobs:
 if name=="cl-native-projection-direct":continue
 objects=[str(OBJ/(name+".obj"))]
 if name=="pcgm-projection-direct":objects.append(str(OBJ/"cl-native-projection-direct.obj"))
 run("link-"+name,[str(compiler),"/nologo",*objects,"/Fe"+str(out/(name+".exe")),"/link","/OPT:REF","/OPT:ICF","/MANIFEST:EMBED","/MANIFESTINPUT:"+str(ROOT/"tools/utf8.manifest")])
