: warranty(sym,i64).
: few(sym).
& a warranty(case1,2).
& b warranty(case2,5).
few($x) <- warranty($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
