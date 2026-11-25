: warmup(sym,qty(minute)).
: short(sym).
& a warmup(case1,700@minute).
& b warmup(case2,1400@minute).
short($x) <- warmup($x,$c) & qty_le($c,1000@minute).
? short(case1).
? short(case2).
