: duty(sym,i64).
: few(sym).
& a duty(case1,2).
& b duty(case2,5).
few($x) <- duty($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
