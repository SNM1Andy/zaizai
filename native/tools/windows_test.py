"""Run the original assertion program with the corresponding Windows handle/select/newline conventions."""
import ctypes,msvcrt,os,pathlib,select,subprocess,sys,time
from ctypes import wintypes
real_popen=subprocess.Popen
class PipePopen(real_popen):
 def __init__(self,args,*a,**kw):
    fds=kw.pop("pass_fds",())
    if fds:
        assert len(fds)==1
        args=list(args);f=fds[0];assert str(f)==str(args[-1])
        h=msvcrt.get_osfhandle(f);args[-1]=str(h);info=subprocess.STARTUPINFO()
        info.lpAttributeList={"handle_list":[h]};kw.update(startupinfo=info,close_fds=True)
        prior=os.get_handle_inheritable(h);os.set_handle_inheritable(h,True)
        try:super().__init__(args,*a,**kw)
        finally:os.set_handle_inheritable(h,prior)
    else:super().__init__(args,*a,**kw)
    if isinstance(self.stdin, __import__('io').TextIOWrapper):
        self.stdin.reconfigure(newline="\n")
subprocess.Popen=PipePopen
kernel=ctypes.WinDLL("kernel32",use_last_error=True)
kernel.PeekNamedPipe.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD,ctypes.c_void_p,ctypes.POINTER(wintypes.DWORD),ctypes.c_void_p]
def pipe_wait(rs,ws,es,timeout=None):
 assert rs and not ws and not es
 deadline=time.monotonic()+timeout if timeout is not None else None
 while True:
    ready=[]
    for file in rs:
        n=wintypes.DWORD()
        if not kernel.PeekNamedPipe(msvcrt.get_osfhandle(file.fileno()),None,0,None,ctypes.byref(n),None):
            if ctypes.get_last_error() in (109,233):ready.append(file)
            else:raise ctypes.WinError(ctypes.get_last_error())
        elif n.value:ready.append(file)
    if ready or (deadline is not None and time.monotonic()>=deadline):return ready,[],[]
    time.sleep(.002)
select.select=pipe_wait
orig=pathlib.Path.write_text
def write(p,txt,*args,**kw):return orig(p,txt,*args,**({"newline":"\n"}|kw))
pathlib.Path.write_text=write
sys.argv=sys.argv[1:];path=pathlib.Path(sys.argv[0]).resolve()
code=path.read_text(encoding="utf8").replace("wait(timeout=5)<0","wait(timeout=5)==1")
code=code.replace("wait(timeout=5) in (0,-9)","wait(timeout=5) in (0,1)")
code=code.replace("service.terminate();assert service.wait(timeout=8)==0","service.terminate();assert service.wait(timeout=8)==1")
exec(compile(code,str(path),"exec"),{"__name__":"__main__","__file__":str(path)})
