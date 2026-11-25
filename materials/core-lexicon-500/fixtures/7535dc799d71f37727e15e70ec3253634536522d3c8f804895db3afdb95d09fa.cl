: noise(sym,i64).
: low(sym).
& a noise(case1,15).
& b noise(case2,20).
low($x) <- noise($x,$v) & int_le(12,$v) & int_lt($v,18).
? low(case1).
? low(case2).
