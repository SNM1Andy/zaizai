: population(sym,i64).
: small(sym).
& a population(case1,2).
& b population(case2,5).
small($x) <- population($x,$v) & int_le($v,3).
? small(case1).
? small(case2).
