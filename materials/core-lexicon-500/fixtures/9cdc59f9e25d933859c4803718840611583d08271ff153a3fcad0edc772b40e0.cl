: deadline_day(sym,i64).
: early(sym).
& a deadline_day(task1,2).
& b deadline_day(task2,5).
early($x) <- deadline_day($x,$v) & int_le($v,3).
? early(task1).
? early(task2).
