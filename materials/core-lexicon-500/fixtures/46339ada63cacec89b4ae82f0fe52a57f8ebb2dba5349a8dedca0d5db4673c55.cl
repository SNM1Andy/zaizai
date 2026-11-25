: consecutive(sym,i64).
: few(sym).
& a consecutive(case1,2).
& b consecutive(case2,5).
few($x) <- consecutive($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
