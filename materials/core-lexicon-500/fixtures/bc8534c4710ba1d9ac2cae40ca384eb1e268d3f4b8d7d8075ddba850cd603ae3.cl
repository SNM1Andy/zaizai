: probation(sym,i64).
: few(sym).
& a probation(case1,2).
& b probation(case2,5).
few($x) <- probation($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
