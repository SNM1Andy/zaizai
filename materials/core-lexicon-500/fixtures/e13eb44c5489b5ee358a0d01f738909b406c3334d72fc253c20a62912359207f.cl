: container(sym,i64).
: few(sym).
& a container(case1,2).
& b container(case2,5).
few($x) <- container($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
