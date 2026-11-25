: audit_cycle(sym,i64).
: few(sym).
& a audit_cycle(case1,2).
& b audit_cycle(case2,5).
few($x) <- audit_cycle($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
