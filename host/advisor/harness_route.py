"""One opted utterance through the local DSHarness account provider."""
import hashlib, json, os, re, subprocess, threading
from pathlib import Path

ROOT=Path(__file__).resolve().parent
APP=Path(os.environ.get("ZAIZAI_HARNESS_DIR") or (Path(os.environ["LOCALAPPDATA"])/"Programs"/"DeepSeek Harness"))
EXE=APP/"DeepSeek Harness.exe"
ASAR=APP/"resources"/"app.asar"
CLI=ASAR/"dsh"/"node_modules"/"@deepseek-ai"/"dsh-desktop-host"/"lib"/"cli.js"
PREFIX=b"ZAIZAI_HARNESS_V1 "
OUTCOMES={"STATUS","RECENT_RECEIPT","CLARIFY"}
SAFE=re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uff0c\u3002\u3001\uff1f\uff01\uff1a\uff1b\u201c\u201d\u2018\u2019\u300a\u300b\u300c\u300d\uff08\uff09 ?!,.;:]+")
HAN=re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
PINS={EXE:"93e0e6e31a2db74eb2e4905b3c79e339537f2c7cc9c9ff72eac2ff5d226f6780", ASAR:"14cfd81c9135bf0afb89417543c94f9ecfe09266574452a9b106890c698725ae", ROOT/"harness_translate.mjs":"e4cf783317361a6531b4dad8e214877f1f47c43e520ae2611ce0788f3eef5095", ROOT/"harness_translate.patch.yml":"ef95bb858828dca14a273bfe7a92ed55384b36c9a0e65e5b758494d603806769"}
class Unavailable(Exception):
    pass
def eligible(text):
    return (type(text) is str and 1<=len(text)<=120 and text==text.strip()
            and SAFE.fullmatch(text) is not None and HAN.search(text) is not None)
def installed():
    return EXE.is_file() and ASAR.is_file()
def checked(path,expected):
    if path.resolve()!=path or not path.is_file(): return False
    with path.open("rb") as f:
        return hashlib.file_digest(f,"sha256").hexdigest()==expected
def frame(stream):
    total=0
    while total<65536:
        line=stream.readline(2049)
        if not line or len(line)>2048: raise Unavailable()
        total+=len(line)
        if line.startswith(PREFIX): return json.loads(line[len(PREFIX):])
    raise Unavailable()
def classify(text,*,approved=False):
    if approved is not True or not eligible(text): raise Unavailable()
    p=None
    timer=None
    try:
        if not all(checked(path,digest) for path,digest in PINS.items()): raise Unavailable()
        cwd=ROOT/"harness-work"
        if cwd.resolve()!=cwd or not cwd.is_dir() or any(cwd.iterdir()): raise Unavailable()
        env={k:v for k,v in os.environ.items() if k.upper() in {
            "SYSTEMROOT","WINDIR","SYSTEMDRIVE","USERPROFILE","HOMEDRIVE","HOMEPATH",
            "APPDATA","LOCALAPPDATA","PROGRAMDATA","PROGRAMFILES","PROGRAMFILES(X86)",
            "PATH","PATHEXT","TEMP","TMP","COMSPEC","USERNAME","USERDOMAIN",
            "HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","NO_PROXY"}}
        env.update(ELECTRON_RUN_AS_NODE="1",DSH_PRIMARY_RUNTIME="")
        p=subprocess.Popen([str(EXE),"--expose-internals",str(CLI),"--profile","sdk",
            "--patch",str(ROOT/"harness_translate.patch.yml")],cwd=cwd,env=env,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
        def expire():
            try: p.kill()
            except OSError: pass
        timer=threading.Timer(30,expire)
        timer.daemon=True
        timer.start()
        if frame(p.stdout)!={"ready":True}: raise Unavailable()
        p.stdin.write((json.dumps({"text":text},ensure_ascii=True)+"\n").encode("ascii"))
        p.stdin.flush()
        result=frame(p.stdout)
        if type(result) is not dict or set(result)!={"intent"} or type(result["intent"]) is not str or result["intent"] not in OUTCOMES: raise Unavailable()
        return result["intent"]
    except Exception:
        raise Unavailable() from None
    finally:
        if p is not None:
            try:
                p.stdin.close()
                p.wait(timeout=2)
            except (OSError,subprocess.TimeoutExpired):
                try:
                    p.kill()
                    p.wait(timeout=2)
                except (OSError,subprocess.TimeoutExpired): pass
            if p.stdout is not None: p.stdout.close()
        if timer is not None: timer.cancel()

