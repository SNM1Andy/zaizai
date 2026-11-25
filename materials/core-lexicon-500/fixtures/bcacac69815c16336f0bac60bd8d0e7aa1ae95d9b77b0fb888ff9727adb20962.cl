: day_count(sym,qty(day)).
: short(sym).
& a day_count(case1,700@day).
& b day_count(case2,1400@day).
short($x) <- day_count($x,$c) & qty_le($c,1000@day).
? short(case1).
? short(case2).
