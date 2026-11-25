: natural_days(sym,i64).
: few(sym).
& a natural_days(case1,2).
& b natural_days(case2,5).
few($x) <- natural_days($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
