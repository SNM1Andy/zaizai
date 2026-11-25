: downtime(sym,qty(minute)).
: short(sym).
& a downtime(case1,700@minute).
& b downtime(case2,1400@minute).
short($x) <- downtime($x,$c) & qty_le($c,1000@minute).
? short(case1).
? short(case2).
