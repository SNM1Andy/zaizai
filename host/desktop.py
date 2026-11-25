import ctypes
import json
import os
import re
import queue
import sys
import threading
import time
import traceback
from contextlib import closing
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,simpledialog,messagebox
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parent))
import native as n
import service
from window_base import Dashboard
from gpu_readout import Readout
import life3
import life3_worker

def session_id(label):
    if label=="主会话":return "main"
    return label if service.ID.fullmatch(label) else "s"+n.sha(label.encode())[:30]
class Desktop(Dashboard):
    def __init__(self,r,legacy,verify=False):
        self.legacy=legacy
        self.verify=verify
        self.session="desktop_check" if verify else "main"
        self.last_id=None
        self.last_seen=None
        self.draft={}
        super().__init__(r,self.snapshot())
        self.entry.configure(undo=True)
        conversation=self.chat.master
        caption=conversation.winfo_children()[0]
        for widget in conversation.winfo_children():widget.pack_forget()
        conversation.columnconfigure(0,weight=1)
        conversation.rowconfigure(1,weight=1)
        caption.grid(row=0,column=0,columnspan=2,sticky="w",pady=(0,6))
        self.chat.grid(row=1,column=0,columnspan=2,sticky="nsew")
        self.entry.grid(row=2,column=0,columnspan=2,sticky="ew",pady=6)
        self.send.grid(row=3,column=1,sticky="e")
        self.cancel_button.grid(row=3,column=0,sticky="w")
        # The monitor must scroll on a scaled display, including on a short screen.
        right=self.fields["identity"].master
        tk.Label(right,text="显卡调度",anchor="w",bg="#1b2331",fg="#a4b3c9").pack(fill="x",pady=(6,0))
        tk.Label(right,text="保留 3 GiB · 温度 < 87°C · 负载目标 99%",anchor="w",justify="left",
                 wraplength=355,bg="#1b2331",fg="#edf0f7").pack(fill="x")
        tk.Label(right,text="生命循环",anchor="w",bg="#1b2331",fg="#a4b3c9").pack(fill="x",pady=(8,1))
        self.life_label=tk.Label(right,anchor="w",justify="left",wraplength=350,bg="#1b2331",fg="#edf0f7")
        self.life_label.pack(fill="x")
        self.gpu=Readout()
        self.gpu_label=tk.Label(right,anchor="w",justify="left",wraplength=355,bg="#1b2331",fg="#a2bcff")
        self.gpu_label.pack(fill="x")
        self.sample_gpu()
        right.pack_forget()
        canvas=tk.Canvas(self.monitor,bg="#1b2331",highlightthickness=0)
        scroll=ttk.Scrollbar(self.monitor,orient="vertical",command=canvas.yview)
        scroll.pack(side="right",fill="y");canvas.pack(side="left",fill="both",expand=True)
        canvas.configure(yscrollcommand=scroll.set)
        window=canvas.create_window(0,0,window=right,anchor="nw")
        right.bind("<Configure>",lambda _:canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",lambda e:canvas.itemconfigure(window,width=e.width))
        r.minsize(500,450)
        bar=tk.Frame(r,bg="#10151e")
        bar.pack(side="top",fill="x",before=r.winfo_children()[1],padx=24)
        tk.Label(bar,text="会话",bg="#10151e",fg="#a4b3c9").pack(side="left")
        with closing(service.store()) as db:
            labels=[r[0][8:] for r in db.execute("select name from options where name like 'session:%' order by name")]
            selected=db.execute("select value from options where name='last_session'").fetchone()
        self.names=ttk.Combobox(bar,state="readonly",width=14,values=["主会话",*labels])
        self.names.pack(side="left",padx=5)
        choice=selected[0] if selected and selected[0] in self.names["values"] else "主会话"
        if not verify:self.session=session_id(choice)
        self.names.set(choice if not verify else "桌面验收")
        self.names.bind("<<ComboboxSelected>>",lambda _:self.choose(self.names.get()))
        for label,action in [("新会话",self.new_session),("查找",self.search),("证据",self.evidence),("帮助",lambda:self.popup("帮助",service.HELP))]:
            ttk.Button(bar,text=label,command=action,width=7).pack(side="left",padx=2)
        self.entry.bind("<Shift-Return>",lambda _:None)
        self.r.bind("<Control-f>",lambda _:self.search())
        self.r.bind("<Control-o>",lambda _:self.open_file())
        self.monitor.bind("<Escape>",lambda _:self.monitor.withdraw())
        self.r.protocol("WM_DELETE_WINDOW",self.close)
        self.reload()
        self.refresh(force=True)
        self.r.after(50,self.poll)
        self.r.after(450,self.ready)
    def enter(self,e):
        if e.state & 1:return None
        self.submit()
        return "break"
    def snapshot(self):
        status=service.monitor_state()
        return dict(identity=n.IDENTITY,generation=self.legacy["generation"],tick=self.legacy["tick"],receipt=self.legacy["receipt"],
                    endpoint=status["display"],event=f"宿主记录 {status['turns']} 个回合，最新序号 {status['last_seq'] or 0}",
                    last=self.last_id or "无当前对话回执")
    def ready(self):
        self.r.update_idletasks()
        bindings=service.monitor_state()["slots"]
        cognition=bindings["C"]
        builds=({key:next(v for k,v in cognition["artifacts"].items() if k.endswith(f"/pcgm-{key}.exe")) for key in ("alpha","beta")}
                if cognition.get("provider_type") in {"legacy","joint-native"} and cognition["id"] in {"legacy-pcgm","joint25-pcgm"} and cognition["state"]=="ready" else {})
        self.startup={"pid":os.getpid(),"identity":n.IDENTITY,"ready":True,"current":self.snapshot(),
                      "window_mapped":bool(self.r.winfo_ismapped()),"monitor_mapped":bool(self.monitor.winfo_ismapped()),
                      "startup_ns":time.time_ns(),"dpi":self.r.winfo_fpixels("1i"),"session":self.session,
                      "slot_bindings":bindings,"builds":builds,
                      "gpu_sample":self.gpu_sample,"host_sha256":n.sha(Path(__file__).read_bytes())}
        tmp=n.STATE/("startup-"+str(os.getpid())+".tmp");tmp.write_text(n.canonical(self.startup),encoding="utf8")
        os.replace(tmp,n.STATE/("window-check-start.json" if self.verify else "startup.json"))
        if not self.verify:
            import joint25_window
            joint25_window.start(self)
        if self.verify:
            question="ready_to_use(local_term)" if "--verify-question" in sys.argv else "identity_restored(zaizai)"
            self.entry.insert("1.0","宿主独立窗口验收请求" if "--verify-slots" in sys.argv else "证明 "+question)
            self.send.invoke()
    def sample_gpu(self):
        self.gpu_sample=self.gpu.sample()
        v=self.gpu_sample
        text=(f"当前空闲 {v['free_mib']/1024:.1f} GiB · {v['temp_c']}°C · 利用率 {v['gpu_percent']}%"
              if v else "当前无法读取显卡传感器")
        self.gpu_label.configure(text=text)
        try:
            with closing(service.store()) as db:
                state=life3.monitor(db)
                online=float(state["heartbeat"])>time.time()-15
                self.life_label.configure(text=f"{state['mode']} · "+("运行中" if online else "等待后台")+"\n"+state["latest"][:115])
                if not self.verify and not self.busy and self.r.winfo_ismapped():
                    with db:
                        for key,body in life3.visible_notices(db,self.session,deliver=True):
                            self.proactive(body);life3.delivered(db,key)
        except Exception as exc:self.life_label.configure(text="暂时无法读取生命记录："+str(exc)[:110])
        self.r.after(2000,self.sample_gpu)
    def proactive(self,body):
        self.chat.configure(state="normal")
        self.chat.insert("end","再再主动说  "+body+"\n\n")
        self.chat.configure(state="disabled");self.chat.see("end")
    def choose(self,label):
        if self.busy:return
        self.draft[self.session]=self.entry.get("1.0","end-1c")
        self.session=session_id(label)
        with closing(service.store()) as db,db:db.execute("INSERT OR REPLACE INTO options VALUES('last_session',?)",(label,))
        self.entry.delete("1.0","end");self.entry.insert("1.0",self.draft.get(self.session,""))
        self.reload();self.refresh(force=True)
    def reload(self):
        self.chat.configure(state="normal");self.chat.delete("1.0","end");self.chat.configure(state="disabled")
        self.last_id=None
        with closing(service.store()) as db:
            kinds=dict(db.execute("""SELECT h.request_id,h.frame_kind FROM host31_commits h
                    JOIN requests r ON r.id=h.request_id WHERE r.session=?""",(self.session,)))
        for _,q,a,rid in service.history(self.session):
            self.show(q,a,kinds.get(rid) or "reply")
            if rid:service.deliver(rid);self.last_id=rid
        with closing(service.store()) as db:
            for key,body in life3.visible_notices(db,self.session):self.proactive(body)
            for r in db.execute("SELECT id,phase,error FROM requests WHERE session=? AND phase IN ('unknown','failed','planned','prepared') ORDER BY started",(self.session,)):
                self.show("请求 "+r["id"],r["error"] or "请求已登记，尚未执行。","slot_status")
    def new_session(self):
        if self.busy:return
        label=simpledialog.askstring("新会话","会话名称",parent=self.r)
        if not label or not label.strip():return
        label=label.strip()
        if label not in self.names["values"]:
            self.names.configure(values=[*self.names["values"],label])
            with closing(service.store()) as db,db:db.execute("INSERT OR REPLACE INTO options VALUES(?,?)",("session:"+label,self.session))
        self.names.set(label);self.choose(label)
    def open_file(self):
        if self.busy:return
        state=service.monitor_state()["slots"]["L"]
        formats=[fmt for fmt in state.get("formats",[]) if isinstance(fmt,str) and re.fullmatch(r"\.[a-zA-Z0-9]{1,12}",fmt)]
        types=[("槽件声明的核验文件"," ".join("*"+fmt for fmt in formats))] if state["state"]=="ready" and formats else []
        types.append(("所有文件","*.*"))
        path=filedialog.askopenfilename(parent=self.r,title="选择核验文件",filetypes=types)
        if path:self.entry.delete("1.0","end");self.entry.insert("1.0","编译文件 "+path)
    def popup(self,title,body):
        top=tk.Toplevel(self.r);top.title("再再 3.1 | "+title);top.geometry("700x470")
        view=tk.Text(top,wrap="word",font=("Microsoft YaHei UI",10));scroll=ttk.Scrollbar(top,command=view.yview)
        view.configure(yscrollcommand=scroll.set);scroll.pack(side="right",fill="y");view.pack(expand=True,fill="both")
        view.insert("1.0",body);view.configure(state="disabled");top.bind("<Escape>",lambda _:top.destroy())
    def search(self):
        query=simpledialog.askstring("查找历史","输入当前会话的关键词",parent=self.r)
        if query:
            result=[f"#{seq}  {q}\n{a}" for seq,q,a,_ in service.history(self.session) if query.casefold() in (q+"\n"+a).casefold()]
            self.popup("查找历史","\n\n".join(result) or "没有匹配的回合。")
    def evidence(self):
        if not self.last_id:self.popup("证据","当前会话没有对应的请求。");return
        with closing(service.store()) as db:r=service.row(db,self.last_id)
        self.popup("证据",json.dumps(dict(request=r["id"],phase=r["phase"],delivered=r["delivered"],source=r["source"],
                  input_sha256=r["digest"],frame_kind=r["frame_kind"] or "historical",host_receipt=r["host_receipt"],plan=json.loads(r["plan"]),native_receipt=r["native_receipt"]),indent=2,ensure_ascii=False))
    def submit(self):
        if self.busy:return
        query=self.entry.get("1.0","end-1c").strip()
        if not query:return
        self.busy=True;self.send.configure(state="disabled",text="推理中…");self.names.configure(state="disabled")
        self.entry.delete("1.0","end")
        sid=self.session;rid="t"+uuid4().hex
        def worker():
            try:self.q.put((query,service.process(query,sid,rid,source="desktop"),None))
            except Exception as e:self.q.put((query,None,f"{type(e).__name__} · {e}\n请求 {rid}"))
        threading.Thread(target=worker,daemon=True).start()
    def refresh(self,force=False):
        # Slot removal and settings changes must be visible even when no events are being committed.
        now=time.monotonic()
        if not force and self.last_seen is not None and now-self.last_seen<2:return
        try:
            state=self.snapshot()
            if self.last_id:
                with closing(service.store()) as db:
                    r=service.row(db,self.last_id)
                    state["last"]=self.last_id+(" · 已送达" if r["delivered"] else " · 待显示")
            self.update_state(state);self.last_seen=now
        except Exception as e:self.fields["endpoint"].configure(text=str(e))
    def poll(self):
        try:q,r,error=self.q.get_nowait()
        except queue.Empty:pass
        else:
            self.busy=False;self.send.configure(state="normal",text="发送");self.names.configure(state="readonly")
            self.show(q,error or r["answer"],"slot_status" if error else (r.get("frame_kind") or "reply"))
            if r:self.last_id=r["id"];service.deliver(self.last_id)
            self.refresh(force=True)
            if not self.verify and getattr(self,"joint_qa",None):
                import joint25_window
                joint25_window.after_reply(self,q,r,error)
            if self.verify:
                info=dict(self.startup,request=self.last_id,message_displayed=bool(r and r["answer"] in self.chat.get("1.0","end")),
                          monitor_displayed=bool(r and r["id"] in self.fields["last"].cget("text")),error=error,
                          action="Tk entry -> Send.invoke -> native transaction -> Tk chat and monitor",
                          geometry=[w.winfo_geometry() for w in (self.r,self.monitor,self.entry,self.send)])
                if r:
                    info["questions"]=json.loads(r["plan"]).get("questions",[])
                    info["frame_kind"]=r.get("frame_kind");info["host_receipt"]=r.get("host_receipt")
                    info["status_label_displayed"]=("宿主状态  "+r["answer"] in self.chat.get("1.0","end"))
                name="window-slots.json" if "--verify-slots" in sys.argv else ("window-question.json" if "--verify-question" in sys.argv else "window.json")
                (n.ROOT/"evidence"/name).write_text(n.canonical(info),encoding="utf8")
                self.r.after(50,self.r.destroy);return
        if not self.busy:self.refresh()
        self.r.after(450 if not self.busy else 35,self.poll)
    def close(self):
        if self.busy:self.r.after(150,self.close)
        else:self.r.destroy()

def main():
    verify=any(arg in sys.argv for arg in ("--verify-window","--verify-slots"))
    # Prevent a second launch from creating a competing desktop session.
    kernel=ctypes.WinDLL("kernel32",use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p]
    kernel.CreateMutexW.restype=ctypes.c_void_p
    token=kernel.CreateMutexW(None,False,"Local\\ZaizaiDesktop20"+("Check" if verify else ("JointPreview" if "--joint-preview" in sys.argv else "")))
    if not token:raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error()==183:return
    try:ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except OSError:pass
    with service.writer():
        legacy=service.host_checkpoint()
        service.setup()
    service.recover()
    if not verify and "--joint-preview" not in sys.argv:life3_worker.start()
    r=tk.Tk();Desktop(r,legacy,verify);r.mainloop()
if __name__=="__main__":
    try:main()
    except Exception:
        detail=traceback.format_exc()
        (n.ROOT/"evidence/desktop-error.log").write_text(detail,encoding="utf8")
        if "--verify-window" not in sys.argv and "--verify-slots" not in sys.argv:
            messagebox.showerror("再再 3.1 无法启动",detail[-1100:])
        raise

