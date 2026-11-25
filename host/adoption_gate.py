"""GUI-thread claim for immutable results from a separate verification worker."""
import hashlib, json, secrets
from dataclasses import dataclass
from time import monotonic

def seal(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()

@dataclass(frozen=True)
class Request:
    token: str
    slot: str
    identity: str
    manifest: str
    deadline: float

class AdoptionGate:
    def __init__(self, clock=monotonic):
        self.clock=clock
        self.pending=None
        self.accepted=None

    def begin(self, slot, identity, manifest, seconds=15):
        if slot not in {"snapshot","restore","native-current"} or not identity.startswith("TEST-R28-") or len(manifest)!=64:
            raise ValueError("INVALID_RECOVERY_CONTEXT")
        if not 0<seconds<=30:
            raise ValueError("INVALID_DEADLINE")
        self.pending=Request(secrets.token_hex(16),slot,identity,manifest,self.clock()+seconds)
        return self.pending

    def cancel(self, request):
        if request!=self.pending:
            return False
        self.pending=None
        return True

    def commit(self, request, result, observed_sha):
        if request!=self.pending:
            return "STALE"
        self.pending=None
        if self.clock()>=request.deadline:
            return "TIMEOUT"
        if (type(result) is not dict or result.get("stage")!=("RESTRICTED_NATIVE_CURRENT_READ_ONLY" if request.slot=="native-current" else "CLOSED_SYNTHETIC_PAIR_ONLY")
            or result.get("slot")!=request.slot or result.get("identity")!=request.identity
            or result.get("manifest")!=request.manifest or seal(result)!=observed_sha):
            return "REJECTED"
        self.accepted=json.loads(json.dumps(result))
        return "VERIFIED"

if __name__=="__main__":
    clock=[0]
    g=AdoptionGate(lambda:clock[0])
    ident="TEST-R28-synthetic"; pin="a"*64
    a=g.begin("snapshot",ident,pin)
    result=dict(stage="CLOSED_SYNTHETIC_PAIR_ONLY",slot="snapshot",identity=ident,manifest=pin,receipt="old")
    assert g.commit(a,result,seal(result))=="VERIFIED"
    baseline=g.accepted.copy()
    b=g.begin("snapshot",ident,pin)
    assert g.cancel(b)
    assert g.commit(b,dict(result,receipt="late"),seal(dict(result,receipt="late")))=="STALE"
    assert g.accepted==baseline
    c=g.begin("snapshot",ident,pin)
    assert g.commit(c,dict(result,receipt="changed"),seal(result))=="REJECTED"
    d=g.begin("snapshot",ident,pin)
    e=g.begin("restore",ident,pin)
    assert g.commit(d,result,seal(result))=="STALE"
    wrong=dict(result,slot="restore",manifest="b"*64)
    assert g.commit(e,wrong,seal(wrong))=="REJECTED"
    f=g.begin("restore",ident,pin,seconds=1)
    clock[0]=1
    right=dict(result,slot="restore",receipt="fresh")
    assert g.commit(f,right,seal(right))=="TIMEOUT"
    assert g.accepted==baseline
    h=g.begin("restore",ident,pin)
    assert g.commit(h,right,seal(right))=="VERIFIED"
    assert g.accepted["receipt"]=="fresh"
    right["receipt"]="later-mutated"
    assert g.accepted["receipt"]=="fresh"
    assert g.commit(h,right,seal(right))=="STALE"
    print("PASS: initial commit, both late cases, bad payload hash, wrong manifest, timeout, fresh restore, no mutation or double adoption")
