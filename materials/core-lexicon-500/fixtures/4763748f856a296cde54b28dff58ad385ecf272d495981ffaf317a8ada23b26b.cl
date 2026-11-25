: overtime_hours(sym,qty(hour)).
: short(sym).
& a overtime_hours(case1,700@hour).
& b overtime_hours(case2,1400@hour).
short($x) <- overtime_hours($x,$c) & qty_le($c,1000@hour).
? short(case1).
? short(case2).
