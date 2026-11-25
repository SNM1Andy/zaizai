: timeout_ms(sym,qty(ms)).
: short(sym).
& a timeout_ms(case1,45@ms).
& b timeout_ms(case2,60@ms).
short($x) <- timeout_ms($x,$c) & qty_lt($c,50@ms).
? short(case1).
? short(case2).
