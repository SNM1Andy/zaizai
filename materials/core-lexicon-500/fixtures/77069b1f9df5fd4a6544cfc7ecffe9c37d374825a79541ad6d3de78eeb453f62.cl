: comp_time(sym,i64).
: few(sym).
& a comp_time(case1,2).
& b comp_time(case2,5).
few($x) <- comp_time($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
