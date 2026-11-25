: sla(sym,qty(ms)).
: met(sym).
& a sla(svc1,30@ms).
& b sla(svc2,90@ms).
met($x) <- sla($x,$c) & qty_le($c,60@ms).
? met(svc1).
? met(svc2).
