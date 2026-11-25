: period_days(sym,qty(day)).
: short(sym).
& a period_days(case1,3@day).
& b period_days(case2,9@day).
short($x) <- period_days($x,$c) & qty_le($c,5@day).
? short(case1).
? short(case2).
