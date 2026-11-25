import json
import os
from pathlib import Path
import subprocess
import threading
from uuid import uuid4

BASE=Path(__file__).resolve().parent/"advisor"
APP=Path(os.environ.get("ZAIZAI_HARNESS_DIR") or (Path(os.environ["LOCALAPPDATA"])/"Programs"/"DeepSeek Harness"))
EXE=APP/"DeepSeek Harness.exe"
CLI=APP/"resources/app.asar/dsh/node_modules/@deepseek-ai/dsh-desktop-host/lib/cli.js"

def consult(term,task):
    if not 0<len(term)<=160:raise ValueError("咨询片段须为 1 至 160 个字符")
    env=dict(os.environ,ELECTRON_RUN_AS_NODE="1",DSH_PRIMARY_RUNTIME="")
    command=[str(EXE),"--expose-internals",str(CLI),"--profile","sdk","--patch",str(BASE/"terms.patch.yml")]
    with subprocess.Popen(command,cwd=BASE,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW) as p:
        timer=threading.Timer(38,p.kill);timer.daemon=True;timer.start()
        try:
            def frame():
                for line in p.stdout:
                    if line.startswith(b"ZAIZAI_ADVICE "):
                        return json.loads(line[len(b"ZAIZAI_ADVICE "):])
                raise RuntimeError("DSHarness 连接结束或超时")
            if frame()!={"ready":True}:raise RuntimeError("握手不匹配")
            p.stdin.write((json.dumps(dict(term=term,task=task))+"\n").encode());p.stdin.flush()
            answer=frame()
            if answer.get("task")!=task:raise RuntimeError("咨询任务号不一致")
            if "error" in answer:raise RuntimeError(answer["error"])
            return answer
        finally:
            timer.cancel()
            if p.poll() is None:p.kill()

