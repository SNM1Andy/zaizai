: sprint(sym,i64).
: few(sym).
& a sprint(case1,2).
& b sprint(case2,5).
few($x) <- sprint($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
