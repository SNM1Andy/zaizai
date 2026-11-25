: metric(sym,i64).
: normal(sym).
& a metric(case1,15).
& b metric(case2,20).
normal($x) <- metric($x,$v) & int_le(12,$v) & int_lt($v,18).
? normal(case1).
? normal(case2).
