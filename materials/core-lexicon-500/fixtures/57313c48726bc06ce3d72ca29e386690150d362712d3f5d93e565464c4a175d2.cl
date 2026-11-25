: calendar_days(sym,i64).
: few(sym).
& a calendar_days(case1,2).
& b calendar_days(case2,5).
few($x) <- calendar_days($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
