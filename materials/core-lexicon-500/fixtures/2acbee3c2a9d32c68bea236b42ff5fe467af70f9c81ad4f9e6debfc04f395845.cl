: iteration(sym,i64).
: few(sym).
& a iteration(case1,2).
& b iteration(case2,5).
few($x) <- iteration($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
