: settlement(sym,i64).
: few(sym).
& a settlement(case1,2).
& b settlement(case2,5).
few($x) <- settlement($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
