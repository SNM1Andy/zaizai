: ttl_hours(sym,qty(hour)).
: short(sym).
& a ttl_hours(case1,700@hour).
& b ttl_hours(case2,1400@hour).
short($x) <- ttl_hours($x,$c) & qty_le($c,1000@hour).
? short(case1).
? short(case2).
