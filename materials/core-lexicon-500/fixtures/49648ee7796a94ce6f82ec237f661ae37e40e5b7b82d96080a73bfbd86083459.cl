: concurrent(sym,i64).
: few(sym).
& a concurrent(case1,2).
& b concurrent(case2,5).
few($x) <- concurrent($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
