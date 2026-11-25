: sample(sym,i64).
: small(sym).
& a sample(case1,2).
& b sample(case2,5).
small($x) <- sample($x,$v) & int_le($v,3).
? small(case1).
? small(case2).
