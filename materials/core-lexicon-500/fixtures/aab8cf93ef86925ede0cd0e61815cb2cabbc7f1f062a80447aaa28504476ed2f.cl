: hour_count(sym,qty(hour)).
: short(sym).
& a hour_count(case1,700@hour).
& b hour_count(case2,1400@hour).
short($x) <- hour_count($x,$c) & qty_le($c,1000@hour).
? short(case1).
? short(case2).
