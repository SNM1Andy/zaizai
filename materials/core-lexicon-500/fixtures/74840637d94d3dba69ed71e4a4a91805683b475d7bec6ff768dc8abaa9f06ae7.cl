: maintenance_window(sym,qty(minute)).
: short(sym).
& a maintenance_window(case1,700@minute).
& b maintenance_window(case2,1400@minute).
short($x) <- maintenance_window($x,$c) & qty_le($c,1000@minute).
? short(case1).
? short(case2).
