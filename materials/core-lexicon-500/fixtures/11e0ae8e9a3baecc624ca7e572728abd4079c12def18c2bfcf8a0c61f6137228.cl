: reconciliation_cycle(sym,i64).
: few(sym).
& a reconciliation_cycle(case1,2).
& b reconciliation_cycle(case2,5).
few($x) <- reconciliation_cycle($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
