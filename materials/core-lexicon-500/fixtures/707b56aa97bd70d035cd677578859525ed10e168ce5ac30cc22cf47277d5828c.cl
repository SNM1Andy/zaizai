: queue_time(sym,qty(minute)).
: short(sym).
& a queue_time(case1,700@minute).
& b queue_time(case2,1400@minute).
short($x) <- queue_time($x,$c) & qty_le($c,1000@minute).
? short(case1).
? short(case2).
