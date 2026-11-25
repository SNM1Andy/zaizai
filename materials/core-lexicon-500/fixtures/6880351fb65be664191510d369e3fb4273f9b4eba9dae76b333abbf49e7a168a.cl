: dashboard(sym,i64).
: few(sym).
& a dashboard(case1,2).
& b dashboard(case2,5).
few($x) <- dashboard($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
