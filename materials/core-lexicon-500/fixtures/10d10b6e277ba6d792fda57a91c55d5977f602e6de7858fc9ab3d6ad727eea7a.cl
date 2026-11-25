: oncall(sym,i64).
: few(sym).
& a oncall(case1,2).
& b oncall(case2,5).
few($x) <- oncall($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
