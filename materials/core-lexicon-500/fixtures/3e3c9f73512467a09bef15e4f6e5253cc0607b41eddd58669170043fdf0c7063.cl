: timer(sym,qty(minute)).
: short(sym).
& a timer(case1,700@minute).
& b timer(case2,1400@minute).
short($x) <- timer($x,$c) & qty_le($c,1000@minute).
? short(case1).
? short(case2).
