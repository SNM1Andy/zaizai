: qps(sym,i64).
: few(sym).
& a qps(case1,2).
& b qps(case2,5).
few($x) <- qps($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
