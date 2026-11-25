: retention_days(sym,i64).
: short(sym).
& a retention_days(case1,2).
& b retention_days(case2,5).
short($x) <- retention_days($x,$v) & int_le($v,3).
? short(case1).
? short(case2).
