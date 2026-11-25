"""Replay the supplied contested civic proof as a transient input to the installed engine."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"host"))
import native as n
def main():
    source=(ROOT/"reference-proof/civic.cl").read_text(encoding="utf8")
    base=source+"\n& report_uniform uniform_implementation(informed).\n& report_pro informed_center(informed).\n"
    contra="& report_con !informed_center(informed).\n"
    alternate="& independent_rollout coordinated_rollout_possible(informed).\n"
    cases=[("both",base+contra,"DIRECT_DISPUTE","DISPUTED_ANCESTRY"),
           ("alternate",base+contra+alternate,"DIRECT_DISPUTE","CLEAN_WITNESS"),
           ("withdraw_con",base,"CLEAN_WITNESS","CLEAN_WITNESS"),
           ("restore_con",base+contra,"DIRECT_DISPUTE","DISPUTED_ANCESTRY")]
    out={}
    for case,src,direct,indirect in cases:
        p=ROOT/"evidence"/("proof-"+case+".cl");p.write_bytes(src.encode())
        wire=n.run(n.exe("alpha"),p,data=b":proof_integrity informed_center(informed)\n:proof_integrity coordinated_rollout_possible(informed)\n:proof_integrity better_overall(china,usa)\n").decode()
        assert "informed_center(informed) positive="+direct in wire and "coordinated_rollout_possible(informed) positive="+indirect in wire and "better_overall(china,usa) positive=NO_SUPPORT" in wire,wire
        out[case]=wire
    (ROOT/"evidence/proof-integrity.json").write_text(n.canonical(out),encoding="utf8")
    print("direct conflict, disputed dependency, independent proof, withdraw/restore, unknown: verified")
if __name__=="__main__":main()

