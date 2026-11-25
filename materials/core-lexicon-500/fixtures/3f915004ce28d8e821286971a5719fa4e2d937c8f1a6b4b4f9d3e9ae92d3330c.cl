: custody_days(sym,i64).
: few(sym).
& a custody_days(case1,2).
& b custody_days(case2,5).
few($x) <- custody_days($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
