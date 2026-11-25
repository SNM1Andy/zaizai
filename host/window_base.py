import tkinter as tk
import queue
class Dashboard:
    def __init__(self,r,state):
        self.r=r
        self.state=state
        self.rows=[]
        self.busy=False
        self.q=queue.Queue()
        dark='#10151e'; card='#1b2331'; fg='#edf0f7'; muted='#a4b3c9'; blue='#a2bcff'
        r.configure(bg=dark);r.title('再再 3.1 | 对话');r.geometry('670x650+18+34');r.minsize(500,420)
        head=tk.Frame(r,bg=dark,padx=26,pady=18);head.pack(fill='x')
        tk.Label(head,text='\u518d\u518d',font=('Microsoft YaHei UI',25,'bold'),bg=dark,fg=fg).pack(side='left')
        tk.Label(head,text='  /  3.1  ·  Windows',font=('Microsoft YaHei UI',11),bg=dark,fg=blue).pack(side='left',padx=12)
        wrap=tk.Frame(r,bg=dark,padx=24,pady=8);wrap.pack(fill='both',expand=True)
        wrap.columnconfigure(0,weight=1);wrap.rowconfigure(0,weight=1)
        left=tk.Frame(wrap,bg=card,padx=18,pady=17);left.grid(row=0,column=0,sticky='nsew')
        self.monitor=tk.Toplevel(r)
        self.monitor.title('\u518d\u518d | \u72b6\u6001\u76d1\u6d4b')
        self.monitor.geometry('420x680+704+34');self.monitor.minsize(335,460)
        self.monitor.configure(bg=dark)
        self.monitor.protocol('WM_DELETE_WINDOW',self.monitor.withdraw)
        tk.Button(head,text='\u6253\u5f00\u76d1\u6d4b',command=self.monitor.deiconify,bg=card,fg=blue,relief='flat').pack(side='right')
        right=tk.Frame(self.monitor,bg=card,padx=20,pady=18);right.pack(fill='both',expand=True,padx=12,pady=12)
        for box,label in [(left,'\u5bf9\u8bdd'),(right,'\u72b6\u6001\u76d1\u6d4b')]:
            tk.Label(box,text=label,font=('Microsoft YaHei UI',15,'bold'),bg=card,fg=fg).pack(anchor='w',pady=(0,12))
        self.chat=tk.Text(left,height=13,wrap='word',font=('Microsoft YaHei UI',11),bg='#141c29',fg=fg,relief='flat',padx=13,pady=11,state='disabled');self.chat.pack(fill='both',expand=True)
        self.chat.tag_configure('you',foreground=blue)
        self.entry=tk.Text(left,height=3,wrap='word',bg='#263248',fg=fg,insertbackground=fg,relief='flat',font=('Microsoft YaHei UI',11));self.entry.pack(fill='x',ipady=9,pady=(10,5))
        self.send=tk.Button(left,text='\u53d1\u9001',command=self.submit,bg='#b6c7ff',fg='#141c29',relief='flat',font=('Microsoft YaHei UI',10,'bold'));self.send.pack(side='right')
        self.cancel_button=tk.Button(left,text="打开核验文件",command=self.open_file,bg=card,fg=blue,relief='flat');self.cancel_button.pack(side='left')
        self.entry.bind('<Return>',self.enter)
        self.fields={}
        for key,title in [('identity','\u8eab\u4efd'),('generation','\u4ee3\u6b21'),('tick','\u8fd0\u884c\u523b\u5ea6'),('receipt','\u5df2\u5b58 M5 \u56de\u6267'),('endpoint','语言槽 / 认知槽'),('event','宿主事件'),('last','对话事务 / 送达')]:
            tk.Label(right,text=title,font=('Microsoft YaHei UI',10),bg=card,fg=muted).pack(anchor='w',pady=(7,2))
            v=tk.Label(right,bg=card,fg=fg,justify='left',wraplength=275,font=('Microsoft YaHei UI',10));v.pack(anchor='w')
            self.fields[key]=v
        tk.Label(right,text='M5、代次与 tick 来自启动时读回的存档。',bg=card,fg=blue,font=('Microsoft YaHei UI',9)).pack(anchor='w',pady=(13,0))
        for _,_,q,a,_ in self.rows:self.show(q,a)
        self.update_state(state)
    def show(self,q,a,frame_kind="reply"):
        label={"host_data":"宿主记录","slot_status":"宿主状态"}.get(frame_kind,"再再")
        self.chat.configure(state='normal');self.chat.insert('end','\u4f60  '+q+'\n','you');self.chat.insert('end',label+'  '+a+'\n\n');self.chat.configure(state='disabled');self.chat.see('end')
    def update_state(self,c):
        self.state=c
        for k,w in self.fields.items():w.configure(text=str(c[k]))
