: cooldown(sym,qty(minute)).
: short(sym).
& a cooldown(case1,700@minute).
& b cooldown(case2,1400@minute).
short($x) <- cooldown($x,$c) & qty_le($c,1000@minute).
? short(case1).
? short(case2).
