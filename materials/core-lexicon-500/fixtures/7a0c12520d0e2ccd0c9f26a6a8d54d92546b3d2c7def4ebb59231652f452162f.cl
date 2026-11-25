: license(sym,i64).
: few(sym).
& a license(case1,2).
& b license(case2,5).
few($x) <- license($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
