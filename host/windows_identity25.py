"""Read the user SID, elevation, logon session and integrity level of the Zaizai and desktop-shell processes."""
import ctypes as c
from ctypes import wintypes as wt
import json,os,sys
from pathlib import Path
K=c.WinDLL("kernel32",use_last_error=True);A=c.WinDLL("advapi32",use_last_error=True);U=c.WinDLL("user32",use_last_error=True)
K.OpenProcess.argtypes=[wt.DWORD,wt.BOOL,wt.DWORD];K.OpenProcess.restype=wt.HANDLE
K.CloseHandle.argtypes=[wt.HANDLE];K.LocalFree.argtypes=[c.c_void_p]
A.OpenProcessToken.argtypes=[wt.HANDLE,wt.DWORD,c.POINTER(wt.HANDLE)]
A.GetTokenInformation.argtypes=[wt.HANDLE,c.c_int,c.c_void_p,wt.DWORD,c.POINTER(wt.DWORD)]
A.ConvertSidToStringSidW.argtypes=[c.c_void_p,c.POINTER(c.c_void_p)]
U.GetShellWindow.restype=wt.HWND;U.GetWindowThreadProcessId.argtypes=[wt.HWND,c.POINTER(wt.DWORD)]
def info(pid):
    proc=K.OpenProcess(0x1000,False,pid)
    if not proc:raise c.WinError(c.get_last_error())
    token=wt.HANDLE()
    try:
        if not A.OpenProcessToken(proc,8,c.byref(token)):raise c.WinError(c.get_last_error())
        def query(cls):
            count=wt.DWORD(0)
            A.GetTokenInformation(token,cls,None,0,c.byref(count));buf=c.create_string_buffer(count.value)
            if not A.GetTokenInformation(token,cls,buf,len(buf),c.byref(count)):raise c.WinError(c.get_last_error())
            return buf
        def sid(cls):
            buf=query(cls);ptr=c.cast(buf,c.POINTER(c.c_void_p)).contents.value;string=c.c_void_p()
            if not A.ConvertSidToStringSidW(ptr,c.byref(string)):raise c.WinError(c.get_last_error())
            try:return c.wstring_at(string.value)
            finally:K.LocalFree(string)
        return {"pid":pid,"account_sid":sid(1),"integrity_sid":sid(25),"elevated":bool(wt.DWORD.from_buffer(query(20)).value),
                "session":wt.DWORD.from_buffer(query(12)).value}
    finally:
        if token:K.CloseHandle(token)
        K.CloseHandle(proc)
def compare(pid):
    h=U.GetShellWindow();p=wt.DWORD()
    if not h or not U.GetWindowThreadProcessId(h,c.byref(p)):raise OSError("当前Windows会话未取得桌面Shell")
    worker=info(pid);shell=info(p.value);same=all(worker[k]==shell[k] for k in ("account_sid","elevated","integrity_sid","session"))
    return {"application":worker,"desktop_shell":shell,"same_account_integrity_elevation_session":same}
if __name__=="__main__":
    root=Path(__file__).resolve().parents[1];pid=json.loads((root/"state/startup.json").read_bytes())["pid"];result=compare(pid)
    (root/"evidence/joint25/windows-token.json").write_text(json.dumps(result,indent=2),encoding="utf8")
    print("same",result["same_account_integrity_elevation_session"],"level",result["application"]["integrity_sid"],"elevated",result["application"]["elevated"])

