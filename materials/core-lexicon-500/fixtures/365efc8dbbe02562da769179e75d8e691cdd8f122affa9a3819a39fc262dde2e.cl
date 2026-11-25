: lease_term(sym,i64).
: few(sym).
& a lease_term(case1,2).
& b lease_term(case2,5).
few($x) <- lease_term($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
