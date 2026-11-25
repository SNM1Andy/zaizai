: seasonality(sym,i64).
: short(sym).
& a seasonality(case1,2).
& b seasonality(case2,5).
short($x) <- seasonality($x,$v) & int_le($v,3).
? short(case1).
? short(case2).
