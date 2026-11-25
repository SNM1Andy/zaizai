: mtbf(sym,qty(day)).
: short(sym).
& a mtbf(case1,3@day).
& b mtbf(case2,9@day).
short($x) <- mtbf($x,$c) & qty_le($c,5@day).
? short(case1).
? short(case2).
