: minute_count(sym,qty(minute)).
: short(sym).
& a minute_count(case1,700@minute).
& b minute_count(case2,1400@minute).
short($x) <- minute_count($x,$c) & qty_le($c,1000@minute).
? short(case1).
? short(case2).
