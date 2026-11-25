: pager(sym,i64).
: high(sym).
& a pager(case1,15).
& b pager(case2,20).
high($x) <- pager($x,$v) & int_le(12,$v) & int_lt($v,18).
? high(case1).
? high(case2).
