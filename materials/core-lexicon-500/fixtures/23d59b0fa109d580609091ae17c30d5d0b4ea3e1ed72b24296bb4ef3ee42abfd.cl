: bias(sym,i64).
: low(sym).
& a bias(case1,15).
& b bias(case2,20).
low($x) <- bias($x,$v) & int_le(12,$v) & int_lt($v,18).
? low(case1).
? low(case2).
