: second(sym,qty(second)).
: short(sym).
& a second(case1,700@second).
& b second(case2,1400@second).
short($x) <- second($x,$c) & qty_le($c,1000@second).
? short(case1).
? short(case2).
