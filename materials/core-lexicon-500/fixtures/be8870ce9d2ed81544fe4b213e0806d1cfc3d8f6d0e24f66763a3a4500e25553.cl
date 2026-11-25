: working_days(sym,i64).
: few(sym).
& a working_days(case1,2).
& b working_days(case2,5).
few($x) <- working_days($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
