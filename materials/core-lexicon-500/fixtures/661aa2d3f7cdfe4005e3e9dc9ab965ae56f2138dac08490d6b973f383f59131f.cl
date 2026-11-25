: aging_days(sym,i64).
: few(sym).
& a aging_days(case1,2).
& b aging_days(case2,5).
few($x) <- aging_days($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
