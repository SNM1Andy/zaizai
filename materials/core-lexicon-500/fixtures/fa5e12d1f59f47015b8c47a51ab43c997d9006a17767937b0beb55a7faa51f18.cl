: raised(sym).
: escalated(sym).
: resolved(sym).
& a raised(sla1).
escalated($x) <- raised($x).
resolved($x) <- escalated($x).
? resolved(sla1).
? resolved(sla2).
