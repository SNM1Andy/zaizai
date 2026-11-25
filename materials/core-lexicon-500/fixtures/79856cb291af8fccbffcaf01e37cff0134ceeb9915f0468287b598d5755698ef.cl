: year_count(sym,i64).
: few(sym).
& a year_count(case1,2).
& b year_count(case2,5).
few($x) <- year_count($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
