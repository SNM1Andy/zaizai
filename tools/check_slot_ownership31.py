"""Check the host's memory boundary and blinded fixed workbook against a private database."""
from pathlib import Path
from contextlib import closing
import argparse, hashlib,json,sqlite3,sys,time
def main(root,out):
    root=root.resolve();sys.path.insert(0,str(root/"host"))
    import host_memory31 as m,host_exam31,study3,slots31
    db=sqlite3.connect(":memory:");db.row_factory=sqlite3.Row
    m.setup(db);slots31.setup(db)
    def observed(key,owner,content):
        m.observe(db,key,"dialogue",content,"local:teaching","用户",{"session":owner,"kind":"dialogue","input_version":"v1"})
    observed("A","s1","纠正：观察应带来源");observed("B","s1","纠正：观察应带来源")
    observed("counter","s1","与此假设相反的记录");observed("other","s2","另一个会话")
    ar=m.search(db,owner="s1",query="观察",limit=8)
    assert len(ar)==2 and len({v for r in ar for v in json.loads(r["source_families"])})==1
    assert not m.search(db,owner="s1",query="另一个")
    def add(id,body,parents,opp=(),**fields):
        m.propose(db,{"id":id,"kind":"semantic","content":body,"parents":list(parents),"contrary":list(opp),**fields},owner="s1",source_ref="slot-unit")
    def reject(fn):
        try:fn()
        except (ValueError,sqlite3.IntegrityError):return
        raise AssertionError("宿主接受了无效的记忆操作")
    add("derived:1","待核验",["A","B"],["counter"]);add("derived:2","子假设",["derived:1"])
    def latest(id):return m.handle(db,{"operation":"read","filter":{"query":id}},owner="s1")["records"][0]
    v=latest("derived:1")
    assert v["contrary"]==["counter"] and v["basis_state"]=="pinned" and len(v["source_families"])==1
    reject(lambda:add("derived:1","回声自证",["derived:2"],["counter"],revision=2,supersedes=v["content_sha256"]))
    reject(lambda:add("derived:1","取消反证",["A"],revision=2,supersedes=v["content_sha256"]))
    add("derived:1","撤回假设",["A"],["counter"],revision=2,supersedes=v["content_sha256"],status="withdrawn")
    assert latest("derived:2")["basis_state"]=="review_required"
    reject(lambda:db.execute("delete from host31_memory where id='counter'"))
    assert db.execute("select count(*) from host31_memory where id='derived:1'").fetchone()[0]==2
    with db:slots31.bind(db,language="legacy-cl",cognition="legacy-pcgm")
    spec=study3.asset("operational_examples.json")["C-01"]
    frozen=study3.asset("frozen_exams.json")["C-01"]
    rules=host_exam31.induce(db,spec["training"])
    independent,measured=host_exam31.examine(db,rules,frozen["independent"])
    transfer,held=host_exam31.examine(db,rules,frozen["transfer"])
    assert independent and transfer and "expected" not in measured["program"] and "expected" not in held["program"]
    with db:slots31.bind(db,language="empty",cognition="empty")
    try:host_exam31.examine(db,rules,frozen["independent"])
    except slots31.SlotUnavailable:pass
    else:raise AssertionError("空槽产生了考试答案")
    result=dict(passed=True,source_families=1,contrary_retained=True,scope_separated=True,cycle_refused=True,
                retraction_revisits_dependents=True,original_revisions=2,independent_exam=independent,transfer=transfer,
                successes=[measured["proof_sha256"],held["proof_sha256"]],empty_cannot_pass=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf8");db.close()
    print("passed source, revision, conflict and blinded workbook checks")
if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--root",type=Path,required=True);parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args();main(args.root,args.out)

