"""Retain the installed Tk two-window layout and replace the Sandbox-dependent host calls."""
from pathlib import Path
root=Path(__file__).resolve().parents[1]
old=(root/"rollback/desktop.py").read_text(encoding="utf8")
base=old[old.index("class Dashboard:"):old.index("    def cancel(self):")]
start=base.index("        self.r=r;")
end=base.index("        dark=",start)
base=base[:start]+'''        self.r=r
        self.state=state
        self.rows=[]
        self.busy=False
        self.q=queue.Queue()
'''+base[end:]
base=base.replace(r"\u672c\u5730\u7248  \u00b7  \u53d7\u9650\u4e2a\u4f53","2.0  ·  Windows").replace(r"\u518d\u518d | \u672c\u5730\u7248","再再 2.0 | 对话")
base=base.replace("self.cancel_button=tk.Button","self.cancel_button=tk.Button").replace('command=self.cancel','command=self.open_file').replace(r'text="\u53d6\u6d88"','text="打开 CL 文件"')
base=base.replace("self.entry=tk.Entry(left", "self.entry=tk.Text(left,height=3,wrap='word'").replace("self.entry.bind('<Return>',lambda _:self.submit())","self.entry.bind('<Return>',self.enter)")
base=base.replace(r"('opens','\u6062\u590d\u65f6\u91cd\u65b0\u8bfb\u53d6')","('endpoint','当前端点 / 版本'),('event','当前事件 / 观察版本'),('last','对话事务 / 送达')")
base=base.replace("r.geometry('595x560+18+34')","r.geometry('670x650+18+34')").replace("self.monitor.geometry('370x510+628+65')","self.monitor.geometry('420x680+704+34')").replace("self.monitor.minsize(320,390)","self.monitor.minsize(335,460)")
base=base.replace("self.update_state(state);r.after(35,self.poll)","self.update_state(state)")
base=base.replace(r"\u72b6\u6001\u6765\u81ea\u72ec\u7acb\u7684\u539f\u751f\u6062\u590d\u8fdb\u7a0b","M5、代次与 tick 来自启动时读回的存档。")
base=base.replace("self.send.pack(anchor='e')","self.send.pack(side='right')").replace("self.cancel_button.pack(anchor='e')","self.cancel_button.pack(side='left')")
(root/"host/window_base.py").write_bytes(("import tkinter as tk\nimport queue\n"+base).encode())

