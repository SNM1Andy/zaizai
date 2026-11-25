: month_count(sym,i64).
: few(sym).
& a month_count(case1,2).
& b month_count(case2,5).
few($x) <- month_count($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
