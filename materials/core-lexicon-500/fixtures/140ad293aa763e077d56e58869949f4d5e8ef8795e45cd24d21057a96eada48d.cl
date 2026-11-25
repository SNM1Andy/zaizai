: service_time(sym,qty(minute)).
: short(sym).
& a service_time(case1,700@minute).
& b service_time(case2,1400@minute).
short($x) <- service_time($x,$c) & qty_le($c,1000@minute).
? short(case1).
? short(case2).
