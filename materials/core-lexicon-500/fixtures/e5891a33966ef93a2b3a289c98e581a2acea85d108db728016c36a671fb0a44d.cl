: early_days(sym,qty(day)).
: small(sym).
& a early_days(case1,3@day).
& b early_days(case2,9@day).
small($x) <- early_days($x,$c) & qty_le($c,5@day).
? small(case1).
? small(case2).
