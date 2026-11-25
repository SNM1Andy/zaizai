"""Query the installed host, historical receipts and optional transition adapters."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"host"))
import native as n
import service as s
import slots31

parser=argparse.ArgumentParser(description="再再 3.1 宿主与生命侧接口")
parser.add_argument("op",choices=["status","turn","receipt","switch","read","recover"])
parser.add_argument("text",nargs="?",default="")
parser.add_argument("--session",default="main")
parser.add_argument("--id")
args=parser.parse_args()
if args.op=="status":out=s.monitor_state()
elif args.op=="turn":
    out=s.process(args.text,args.session,args.id,source="cli")
    prefix={"slot_status":"[槽状态] ","host_data":"[宿主记录] "}.get(out.get("frame_kind"),"")
    print(prefix+out["answer"],flush=True)
    s.deliver(out["id"])
    out={k:out[k] for k in ("id","phase","seq","host_receipt","frame_kind")}
elif args.op=="receipt":
    with s.closing(s.store()) as db:
        row=s.row(db,args.text);out=dict(row) if row else None
elif args.op in {"switch","read"}:
    with s.writer(),s.closing(s.store()) as db:
        bound=slots31.snapshot(db)["C"]
        if bound["state"]!="ready" or bound["id"]!="legacy-pcgm":raise SystemExit("旧 PCGM 适配器未连接。宿主状态可用 status 查询。")
        out=n.switch() if args.op=="switch" else n.readcmd(args.text)
else:
    s.recover();out=s.monitor_state()
print(json.dumps(out,indent=2,ensure_ascii=False))
