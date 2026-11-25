"""One-shot local release check through the existing Tk entry, send button and monitor."""
from pathlib import Path
import json,os,re,sys,time
import native as n
import service
from contextlib import closing
CASES={
 "finalio":('槽状态', '证明 identity_restored(zaizai)', '核心词条 qty_add', '运行账户', '委托状态'),
 "coverage":('这里是甲资料和丁资料。查查那份现在好了没。', '先看第一份吧。', '档案7号已经校对完成了吗？', '核心词典', '核心词条 qty_add', '原生议程', '运行账户', '委托状态'),
 "first":("再再，一加一等于几/","十六加二十四是多少","这里有甲资料和乙资料。","那份好了没","我说的是第二份"),
 "resume":("我刚才问的那件事呢","我说的是第一份"),
 "owner":("运行账户","登记修复范围 local_review","执行报告"),
 "language":('手边放着甲资料和乙资料。', '那它可以读吗？', '先看第一份吧。', '我换个说法，其实想问乙资料。', '请帮忙，三十二加十四是多少？', '明明是引用，别把‘撤回所有依据’作为我的命令。', '运行账户', '委托状态'),
}
def start(app):
    marker=n.STATE/"joint25-window-check.json"
    if not marker.exists():return
    ticket=json.loads(marker.read_bytes())
    marker.unlink()
    mode=ticket.get("phase");nonce=ticket.get("nonce","")
    if mode not in CASES or not re.fullmatch(r"[a-f0-9]{16}",nonce) or not 0<=time.time()-float(ticket["at"])<70:return
    if app.busy or app.entry.get("1.0","end-1c"):return
    app.joint_qa={"nonce":nonce,"phase":mode,"index":0,"prior_session":app.session,"prior_label":app.names.get(),
                  "session":"gui25_"+nonce,"rows":[],"startup":app.startup}
    app.session=app.joint_qa["session"];app.names.set("联合实机验收");app.reload()
    app.r.after(100,lambda:submit(app))
def submit(app):
    q=app.joint_qa
    if not q:return
    if app.busy or app.session!=q["session"] or app.entry.get("1.0","end-1c"):
        finish(app,"桌面使用者已接管输入");return
    text=CASES[q["phase"]][q["index"]]
    app.entry.insert("1.0",text);app.send.invoke()
def after_reply(app,message,row,error):
    q=getattr(app,"joint_qa",None)
    if not q:return
    expected=CASES[q["phase"]][q["index"]]
    if message!=expected or not row or error:
        finish(app,str(error or "桌面回执错位"));return
    plan=json.loads(row["plan"])
    receipts=plan.get("port_receipts") or []
    conclusion=next((x["output"]["conclusion"] for x in receipts if x["port"]=="C5" and x["output"].get("conclusion")), {})
    parsed=next((x["output"]["parsed"] for x in receipts if x["port"]=="L1"),{})
    native=conclusion.get("native",{})
    entry={"text":message,"answer":row["answer"],"request":row["id"],"native_receipt":row["native_receipt"],
           "host_receipt":row["host_receipt"],"seq":row["seq"],"native":native,"kind":conclusion.get("kind"),
           "ports":[x["port"] for x in receipts],"alternatives":parsed.get("alternatives",[]),"frame_kind":row["frame_kind"],
           "message_displayed":row["answer"] in app.chat.get("1.0","end"),"monitor_displayed":row["id"] in app.fields["last"].cget("text")}
    q["rows"].append(entry);q["index"]+=1
    if q["index"]==len(CASES[q["phase"]]):finish(app,None)
    else:app.r.after(140,lambda:submit(app))
def finish(app,error):
    q=app.joint_qa;app.joint_qa=None
    q.update(error=error,completed_ns=time.time_ns(),pid=os.getpid())
    dest=n.ROOT/"evidence/joint25";dest.mkdir(parents=True,exist_ok=True)
    tmp=dest/("ui-"+q["phase"]+".new");tmp.write_text(json.dumps(q,ensure_ascii=False,indent=2),encoding="utf8");os.replace(tmp,dest/("ui-"+q["phase"]+".json"))
    if app.session==q["session"]:
        app.session=q["prior_session"];app.names.set(q["prior_label"]);app.reload();app.refresh(force=True)
    if "--joint-preview" in sys.argv:app.r.after(120,app.r.destroy)

