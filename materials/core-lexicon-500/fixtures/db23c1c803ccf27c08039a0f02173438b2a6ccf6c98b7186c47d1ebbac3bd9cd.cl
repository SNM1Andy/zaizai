: gateway(sym,i64).
: few(sym).
& a gateway(case1,2).
& b gateway(case2,5).
few($x) <- gateway($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
