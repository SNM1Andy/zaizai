"""Check upstream withdrawal and equal-size evidence changes through three live CL proof layers."""
from pathlib import Path
import json,sqlite3,sys
r=Path(sys.argv[1]);sys.path.insert(0,str(r/"host"))
import life3 as l
db=sqlite3.connect(":memory:");db.row_factory=sqlite3.Row;l.setup(db)
def feed(topic,origins,pin,deps=()):
 l.flow_event(db,{"kind":"evidence","topic":topic,"source":"fixture","proof":pin,
     "origins":[dict(family=o,sign=1) for o in origins],"dependencies":list(deps)})
def settle():
 result=[]
 for _ in range(10):
  db.execute("update life3_flows set last_run=0")
  e=l.reasoning_step(db)
  if not e:break
  result.append([e["topic"],e["status"],e["basis"]])
 return result
feed("A",["peer"],"first");feed("B",["independent"],"b",["A"]);feed("C",["third"],"c",["B"])
v1=settle();assert [x[1] for x in v1]==["POSITIVE"]*3,v1
feed("A",["peer"],"second-revision")
assert db.execute("select sum(examined) from life3_flows").fetchone()[0]==0
v2=settle();assert all(x[2]!=y[2] for x,y in zip(v1,v2)) and len(v2)==3
feed("A",[],"withdrawn");feed("NEW",["another"],"n",["A"])
v3=settle();assert {x[0] for x in v3}=={"A","B","C","NEW"} and all(x[1]=="UNKNOWN" for x in v3),v3
feed("loop1",["s"],"l1",["loop2"]);feed("loop2",["s"],"l2",["loop1"])
v4=settle();assert all(x[1]=="UNKNOWN" for x in v4) and len(v4)==2
(r/"evidence/v3-flow-versions.json").write_text(json.dumps(dict(original=v1,same_family_new_revision=v2,withdrawal=v3,circular=v4)),encoding="utf8")
print("version pins, transitive withdrawal, independent family and circular cases passed")
