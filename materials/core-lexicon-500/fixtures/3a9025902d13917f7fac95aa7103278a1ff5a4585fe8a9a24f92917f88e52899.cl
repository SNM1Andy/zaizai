: spike(sym,i64).
: flagged(sym).
& a spike(case1,15).
& b spike(case2,20).
flagged($x) <- spike($x,$v) & int_le(12,$v) & int_lt($v,18).
? flagged(case1).
? flagged(case2).
