: workday(sym,i64).
: weekday(sym).
& a workday(day1,2).
& b workday(day2,7).
weekday($x) <- workday($x,$v) & int_le(1,$v) & int_lt($v,6).
? weekday(day1).
? weekday(day2).
