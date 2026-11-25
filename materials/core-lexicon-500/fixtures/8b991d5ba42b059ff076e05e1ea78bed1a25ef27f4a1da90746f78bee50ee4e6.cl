: priority(sym,i64).
: high(sym).
& a priority(case1,15).
& b priority(case2,20).
high($x) <- priority($x,$v) & int_le(12,$v) & int_lt($v,18).
? high(case1).
? high(case2).
