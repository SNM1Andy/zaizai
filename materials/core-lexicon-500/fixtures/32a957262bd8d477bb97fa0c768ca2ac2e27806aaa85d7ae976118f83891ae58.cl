: wait_days(sym,i64).
: few(sym).
& a wait_days(case1,2).
& b wait_days(case2,5).
few($x) <- wait_days($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
