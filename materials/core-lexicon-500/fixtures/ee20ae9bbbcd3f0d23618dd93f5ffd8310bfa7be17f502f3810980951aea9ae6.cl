: probe(sym,i64).
: few(sym).
& a probe(case1,2).
& b probe(case2,5).
few($x) <- probe($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
