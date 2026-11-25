: vulnerability(sym,i64).
: high(sym).
& a vulnerability(case1,15).
& b vulnerability(case2,20).
high($x) <- vulnerability($x,$v) & int_le(12,$v) & int_lt($v,18).
? high(case1).
? high(case2).
