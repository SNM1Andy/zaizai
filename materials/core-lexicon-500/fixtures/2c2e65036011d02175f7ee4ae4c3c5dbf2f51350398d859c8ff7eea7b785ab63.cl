: load_balancer(sym,i64).
: few(sym).
& a load_balancer(case1,2).
& b load_balancer(case2,5).
few($x) <- load_balancer($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
