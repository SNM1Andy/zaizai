: leave_days(sym,i64).
: short_leave(sym).
& a leave_days(trip1,3).
& b leave_days(trip2,7).
short_leave($x) <- leave_days($x,$v) & int_le($v,5).
? short_leave(trip1).
? short_leave(trip2).
