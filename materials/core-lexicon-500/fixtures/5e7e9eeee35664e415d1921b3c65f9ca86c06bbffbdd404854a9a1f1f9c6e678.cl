: anomaly(sym,i64).
: flagged(sym).
& a anomaly(case1,15).
& b anomaly(case2,20).
flagged($x) <- anomaly($x,$v) & int_le(12,$v) & int_lt($v,18).
? flagged(case1).
? flagged(case2).
