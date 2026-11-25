"""Public candidate entry. No host activation mode is exposed by this package."""
import os
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from common import DB, FIXTURES, MODE, canonical, db_open, need, stdin_json, verify_release


def constrain(role):
    """Application check for this fixed fixture code; not a Windows restricted token."""
    opens = []
    readers = FIXTURES / "question-1.txt"
    runtime = Path(sys.base_prefix).resolve()
    run = ROOT/"run"
    mutable_db = (DB, DB.with_name(DB.name+"-journal"))
    def check_path(raw, writing=False):
        if isinstance(raw, int):
            return
        p = Path(os.path.abspath(raw)).resolve()
        if p.is_relative_to(FIXTURES):
            need(role == "reader" and p == readers and not writing and not opens, "FIXTURE_OPEN_DENIED")
            opens.append(str(p.relative_to(ROOT)))
        elif writing:
            need(role in ("run","birth","reader","api") and
                 (p.is_relative_to(run) or p in mutable_db), "WRITE_SCOPE")
        else:
            need(p.is_relative_to(ROOT) or p.is_relative_to(runtime), "READ_SCOPE " + str(p))
    def audit(event, args):
        if event == "open":
            check_path(args[0], args[2] & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_APPEND|os.O_TRUNC))
        elif event == "sqlite3.connect":
            target = os.fspath(args[0])
            m5 = run / "m5-original.sqlite"
            allowed = {p.as_uri()+"?mode=ro" for p in (m5, DB)}
            if role in ("run","api","reader","duplicate"):
                allowed.add(DB.as_uri()+"?mode=rw")
            if role in ("run","api"):
                allowed.add(m5.as_uri()+"?mode=rw")
            for path in (run/"m5-1.sqlite", run/"m5-2.sqlite"):
                if role in ("run","cold"):
                    allowed.add(path.as_uri()+"?mode=ro")
                if role == "run":
                    allowed.update((str(path), path.as_uri()+"?mode=rw"))
            if role == "run":
                allowed.add(str(m5))
            if role == "cold":
                allowed.add(":memory:")
            need(target in allowed, "SQLITE_SCOPE")
        elif event == "subprocess.Popen":
            exe, argv = args[:2]
            allowed = {"run":{"birth","api"}, "api":{"reader"}}.get(role,set())
            prefix = [sys.executable,"-X","utf8","-I","-S","-B",str(ROOT/"entry.py")]
            commands = {subprocess.list2cmdline(prefix+[name,sys.argv[2]]) for name in allowed}
            need(exe in (None,sys.executable) and argv in commands, "CHILD_SCOPE")
        elif event.startswith(("socket.","winreg.","os.spawn","os.exec","os.startfile","os.posix_spawn")) or event in (
                "os.system","os.symlink","os.link","os.chmod","sqlite3.load_extension"):
            raise PermissionError(event)
        elif event in ("os.mkdir","os.remove","os.rmdir","os.utime"):
            check_path(args[0],True)
        elif event == "os.rename":
            for path in args[:2]:
                check_path(path,True)
    sys.addaudithook(audit)
    return opens


def main():
    role, pin = sys.argv[1:]
    need(role in ("run","birth","api","reader","cold","duplicate","gates","check"), "MODE")
    opens = constrain(role)
    plan = verify_release(pin)
    sys.path.insert(0,str(ROOT/"r14/bundle"))
    import base
    pins = base.verified(__import__("provenance").R14_PIN)
    if role in ("check","gates"):
        if role == "check":
            base.enable_numeric(pins)
            from al01.integrated import IntegratedLife
            from al01.folder_broker import FolderBroker
            from cli_frozen import Shell
            import original_action
        return dict(mode=MODE, status="PACKAGE_VERIFIED", r14_original_gates=[base.gate(k) for k in base.DENIALS],
                    files=len(pins["files"]), origins=base.project_origins(pins), pid=os.getpid())
    if role == "reader":
        from m2_reader import read_once
        calls = []
        def observe(frame,event,function):
            if frame.f_code is read_once.__code__ and event == "c_return" and function in (os.open,os.read,os.close):
                calls.append(function.__name__)
        sys.setprofile(observe)
        try:
            result = read_once(pin)
        finally:
            sys.setprofile(None)
        need(opens == [str((FIXTURES/"question-1.txt").relative_to(ROOT))], "EXPECTED_SINGLE_FIXTURE_OPEN")
        need(calls == ["open","read","close"], "READER_CALL_TRACE")
        result["read"].update(read_calls=calls.count("read"), calls=calls, opened_path=opens[0])
        return result
    if role == "api":
        from backend_api import api
        db = db_open(pin)
        try:
            return api(db,plan,stdin_json(),pin)
        finally:
            db.close()
    if role == "cold":
        from cold import verify
        prohibited = {
            "al01.integrated": {"IntegratedLife.step","IntegratedLife._control"},
            "al01.core": {"World.observe","World.movement","Individual.step","Individual.commit"},
            "al01.durable": {"WorldDispatcher.execute_request","WorldDispatcher._adapter"},
            "original_action": {"enroll","decide","complete","transaction"},
            "m2_reader": {"read_once"}, "r12_birth": {"birth"},
            "world_link": {"practice","apply_receipt"}
        }
        blocked = []
        def cold_guard(frame,event,arg):
            if event == "call":
                module = frame.f_globals.get("__name__")
                name = frame.f_code.co_qualname
                if name in prohibited.get(module, ()):
                    blocked.append(module+"."+name)
                    raise PermissionError("COLD_ACTION_DENIED")
        sys.setprofile(cold_guard)
        try:
            result = verify(plan, pin, pins)
        finally:
            sys.setprofile(None)
        need(not blocked and not opens, "COLD_EFFECT")
        return dict(result, cold_blocked_calls=blocked, cold_fixture_opens=len(opens))
    if role == "duplicate":
        from campaign import duplicate
        return duplicate(plan,pin)
    from campaign import birth,run
    return birth(plan,pin,pins) if role=="birth" else run(plan,pin,pins)


if __name__ == "__main__":
    print(canonical(main()),flush=True)
