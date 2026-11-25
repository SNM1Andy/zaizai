: gap_minutes(sym,qty(minute)).
: short(sym).
& a gap_minutes(case1,700@minute).
& b gap_minutes(case2,1400@minute).
short($x) <- gap_minutes($x,$c) & qty_le($c,1000@minute).
? short(case1).
? short(case2).
