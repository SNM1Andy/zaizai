: countdown(sym,qty(day)).
: short(sym).
& a countdown(case1,3@day).
& b countdown(case2,9@day).
short($x) <- countdown($x,$c) & qty_le($c,5@day).
? short(case1).
? short(case2).
