: validity(sym,qty(day)).
: short(sym).
& a validity(case1,3@day).
& b validity(case2,9@day).
short($x) <- validity($x,$c) & qty_le($c,5@day).
? short(case1).
? short(case2).
