: elapsed(sym,qty(minute)).
: short(sym).
& a elapsed(case1,700@minute).
& b elapsed(case2,1400@minute).
short($x) <- elapsed($x,$c) & qty_le($c,1000@minute).
? short(case1).
? short(case2).
