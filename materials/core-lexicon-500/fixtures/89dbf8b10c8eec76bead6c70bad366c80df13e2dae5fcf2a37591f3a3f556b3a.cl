: recovery_time(sym,qty(minute)).
: short(sym).
& a recovery_time(case1,700@minute).
& b recovery_time(case2,1400@minute).
short($x) <- recovery_time($x,$c) & qty_le($c,1000@minute).
? short(case1).
? short(case2).
