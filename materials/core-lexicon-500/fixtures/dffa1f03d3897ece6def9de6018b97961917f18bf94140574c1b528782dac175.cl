: millisecond(sym,qty(ms)).
: short(sym).
& a millisecond(case1,700@ms).
& b millisecond(case2,1400@ms).
short($x) <- millisecond($x,$c) & qty_le($c,1000@ms).
? short(case1).
? short(case2).
