: partition(sym,i64).
: few(sym).
& a partition(case1,2).
& b partition(case2,5).
few($x) <- partition($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
