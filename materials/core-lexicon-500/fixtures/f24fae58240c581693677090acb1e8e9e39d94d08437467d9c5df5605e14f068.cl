: rollout(sym,i64).
: wide(sym).
& a rollout(case1,5).
& b rollout(case2,80).
wide($x) <- rollout($x,$v) & int_le($v,50).
? wide(case1).
? wide(case2).
