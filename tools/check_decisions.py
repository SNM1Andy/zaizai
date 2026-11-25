"""Use labelled Windows acceptance observations on the active individual and withdraw them after review."""
import json,sys,time
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"host"))
import native as n
import service as s
def main():
    key="v"+uuid4().hex[:12]
    log=[]
    def native(line):
        answer=n.execute(line)
        log.append(dict(command=line,out=answer,when_ns=time.time_ns()))
        return answer
    def decision(command):
        d=json.loads(native(command))["decision"]
        return d["status"],(d["options"][d["selected"]]["kind"] if d["selected"] is not None else None)
    existing=n.status()
    with s.writer():
        initial=decision(":compare_versions_parallel_json")
        assert initial[1]=="stay",initial
        # Keep the observation provenance alongside the exact PCGM batch and its head.
        head=json.loads(n.run(n.exe("alpha"),"--desktop-snapshot",n.SAVE))["head"]
        obs=[(key+"a","term_grounded(current)"),(key+"b","term_local_match(current)"),(key+"c","requested_learning(current)")]
        native(":observation_batch "+key+" "+head+"".join(f" ; observe {i} {fact}" for i,fact in obs))
        after=decision(":compare_versions_parallel_json")
        if after[1]!="rewrite":
            (ROOT/"evidence/decision-debug.json").write_text(n.canonical(log),encoding="utf8")
            raise ValueError(after)
        applied=decision(":decide_versions_parallel_json")
        assert applied[1]=="rewrite" and applied[0]=="committed",applied
        native(":withdraw "+key+"c")
        native(":observe "+key+"d reconsider_learning(current)")
        next_choice=decision(":compare_versions_parallel_json")
        assert next_choice[1]=="rollback",next_choice
        rollback=decision(":decide_versions_parallel_json")
        assert rollback[1]=="rollback" and rollback[0]=="committed",rollback
        assert native("reconsider_learning(current)").startswith("POSITIVE")
        for name in ("a","b","d"):native(":withdraw "+key+name)
        restored=decision(":compare_versions_parallel_json")
    report=dict(identity=n.IDENTITY,source="Windows acceptance of native choice, scoped observations",before=existing,
                stay=initial,rewrite=applied,rollback=rollback,last=restored,trace=log)
    (ROOT/"evidence/decisions.json").write_text(n.canonical(report),encoding="utf8")
    print(initial,applied,rollback,restored)
if __name__=="__main__":main()

