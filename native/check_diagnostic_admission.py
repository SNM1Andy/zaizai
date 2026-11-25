"""Exercise one disputed and one clean independent witness through public review and real admission, for each engine."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT=Path(__file__).resolve().parent;CL=ROOT/"bin/cl.exe"
def pin(b):return hashlib.sha256(b).hexdigest()
def run(exe,*args,raw=b"",must=True):
    p=subprocess.run([exe,*args],input=raw,capture_output=True,timeout=25,creationflags=subprocess.CREATE_NO_WINDOW)
    if must and p.returncode:raise RuntimeError((p.stderr+p.stdout).decode("utf8","replace"))
    return p
def test(d,owner):
    d.mkdir();incoming=d/"incoming";incoming.mkdir();pcgm=ROOT/"bin"/("pcgm-"+owner+".exe")
    state=d/"state";subject=d/"subject.cl";subject.write_text(": clue(sym).\n: ready(sym).\nready($x) <- clue($x).\n? ready(alpha).\n")
    run(pcgm,"--init-managed",subject,state,raw=b":ask\n")
    def read(op):
        return json.loads(run(pcgm,"--read-channel",state,raw=("audit "+op+"\n").encode()).stdout)["payload"]
    q=read("question_feed 0 1")["results"][0]
    rule=d/"world.cl";rule.write_text("module world.\n: p(sym).\n: alt(sym).\n: clue(sym).\nclue($x) <- p($x).\nclue($x) <- alt($x).\n")
    lock=d/"lock";lock.write_bytes(run(CL,"lock",rule).stdout);api=d/"api";api.write_bytes(run(CL,"project-api",rule,lock).stdout)
    pkg=d/"pkg";pkg.write_bytes(run(CL,"project-pack",rule,lock,api).stdout);pkgpin=pin(pkg.read_bytes());goal=d/"goal";goal.write_bytes(b"clue(alpha)\n")
    before=pin(state.read_bytes());results={}
    for name,atoms,clean in (("dirty",["p(alpha)","!p(alpha)"],False),("clean",["p(alpha)","!p(alpha)","alt(alpha)"],True)):
        journal=d/(name+".journal");raw=("x batch seed 0"+"".join(f" ; observe a{i} {a}" for i,a in enumerate(atoms))+"\n").encode()
        assert json.loads(run(CL,"evidence-init",pkg,pkgpin,goal,journal,raw=raw).stdout)["ok"]
        js=pin(journal.read_bytes());art=incoming/(name+".clef");art.write_bytes(run(CL,"evidence-freeze",pkg,pkgpin,goal,journal,js).stdout)
        h=pin(art.read_bytes());args=(state,q["id"],q["request_sha256"],art,h,pkgpin,js)
        advisory=json.loads(run(pcgm,"--frozen-question-integrity",*args).stdout)
        assert advisory["clean_signed_advisory"] is clean and advisory["cl_proof"]["results"][0]["status"]=="POSITIVE"
        assert advisory["cl_integrity"]==json.loads(run(CL,"evidence-frozen-integrity",art,h,pkgpin,js).stdout)
        assert pin(state.read_bytes())==before
        # Use the true digest of the freshly re-derived signed proof, not a placeholder that could independently cause refusal.
        proof=advisory["cl_integrity"]["signed_proof_sha256"]
        frame=":admit_frozen "+" ".join((q["id"],q["request_sha256"],name,h,pkgpin,js,proof))+"\n"
        res=run(pcgm,"--resume",state,raw=frame.encode(),must=False);diagnostic=(res.stdout+res.stderr).decode("utf8")
        truth=read("proof ready(alpha)")["results"][0]["status"]
        if clean:
            assert pin(state.read_bytes())!=before and truth=="POSITIVE" and res.returncode==0,(truth,diagnostic)
        else:
            assert "frozen proof depends on disputed premises" in diagnostic and pin(state.read_bytes())==before and truth=="UNKNOWN",(truth,diagnostic)
        results[name]={"artifact_sha256":h,"proof_sha256":proof,"advisory":advisory,"admission_response":diagnostic,
             "native_effect_after_cold_read":truth,"file_unchanged":pin(state.read_bytes())==before}
    return results
if __name__=="__main__":
    with TemporaryDirectory(prefix="zdiagnostic25-") as tmp:rows={build:test(Path(tmp)/build,build) for build in ("alpha","beta")}
    (ROOT/"evidence/diagnosis-and-admission.json").write_text(json.dumps({"passed":True,"builds":rows},indent=2),encoding="utf8")
    print("PASS alpha/beta disputed diagnostic + actual rejection, clean diagnostic + actual admission and cold read")
