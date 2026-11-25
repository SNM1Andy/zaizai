"""Build the upstream standalone Unicode SDK test consumer with Windows binary stdout."""
from pathlib import Path
import build as b

def build_probe():
    target=b.OBJ/"acceptance"
    target.mkdir(exist_ok=True)
    name="cl-unicode-sdk-check"
    exe=target/(name+".exe")
    src=target/(name+".c")
    original=(b.SRC/(name+".c")).read_text(encoding="utf8")
    # This consumer compares UTF-8 protocol bytes with the independent CLI output.
    src.write_bytes(("#include <io.h>\n#include <fcntl.h>\n"+
        original.replace("int main(int argc,char** argv){","int main(int argc,char** argv){\n_setmode(_fileno(stdout),_O_BINARY);")).encode())
    b.run("unicode-sdk-consumer",[str(b.compiler),"/nologo","/std:c11","/utf-8","/MD","/D_CRT_SECURE_NO_WARNINGS",
        "/I"+str(b.SRC),str(src),str(b.BIN/"cl_memory.lib"),"/Fo"+str(target/(name+".obj")),
        "/Fe"+str(exe),"/link","/MANIFEST:EMBED","/MANIFESTINPUT:"+str(b.ROOT/"tools/utf8.manifest")])
    return exe
if __name__=="__main__":print(build_probe())
