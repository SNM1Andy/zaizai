: canary(sym,i64).
: wide(sym).
& a canary(case1,5).
& b canary(case2,50).
wide($x) <- canary($x,$v) & int_le($v,20).
? wide(case1).
? wide(case2).
