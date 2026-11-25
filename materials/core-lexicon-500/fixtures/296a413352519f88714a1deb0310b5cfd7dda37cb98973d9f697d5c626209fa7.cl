: release_window(sym,qty(minute)).
: short(sym).
& a release_window(case1,700@minute).
& b release_window(case2,1400@minute).
short($x) <- release_window($x,$c) & qty_le($c,1000@minute).
? short(case1).
? short(case2).
