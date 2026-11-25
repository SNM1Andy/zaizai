: source_rank(sym,i64).
: high(sym).
& a source_rank(case1,2).
& b source_rank(case2,5).
high($x) <- source_rank($x,$v) & int_le($v,3).
? high(case1).
? high(case2).
