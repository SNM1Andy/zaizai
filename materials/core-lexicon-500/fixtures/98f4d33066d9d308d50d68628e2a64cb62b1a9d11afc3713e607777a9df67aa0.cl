: score(sym,i64).
: high(sym).
& a score(case1,15).
& b score(case2,20).
high($x) <- score($x,$v) & int_le(12,$v) & int_lt($v,18).
? high(case1).
? high(case2).
