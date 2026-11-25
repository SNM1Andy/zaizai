: lag_days(sym,qty(day)).
: small(sym).
& a lag_days(case1,3@day).
& b lag_days(case2,9@day).
small($x) <- lag_days($x,$c) & qty_le($c,5@day).
? small(case1).
? small(case2).
