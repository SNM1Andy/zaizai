: mttr(sym,qty(minute)).
: short(sym).
& a mttr(case1,700@minute).
& b mttr(case2,1400@minute).
short($x) <- mttr($x,$c) & qty_le($c,1000@minute).
? short(case1).
? short(case2).
