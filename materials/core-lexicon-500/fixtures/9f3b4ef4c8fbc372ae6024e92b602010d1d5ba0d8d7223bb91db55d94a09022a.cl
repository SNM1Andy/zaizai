: frequency_per_day(sym,i64).
: low(sym).
& a frequency_per_day(case1,2).
& b frequency_per_day(case2,5).
low($x) <- frequency_per_day($x,$v) & int_le($v,3).
? low(case1).
? low(case2).
