: replica(sym,i64).
: few(sym).
& a replica(case1,2).
& b replica(case2,5).
few($x) <- replica($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
