: window_minutes(sym,qty(minute)).
: short(sym).
& a window_minutes(case1,700@minute).
& b window_minutes(case2,1400@minute).
short($x) <- window_minutes($x,$c) & qty_le($c,1000@minute).
? short(case1).
? short(case2).
