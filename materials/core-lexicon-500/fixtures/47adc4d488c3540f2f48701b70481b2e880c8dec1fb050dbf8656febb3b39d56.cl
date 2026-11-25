: queue(sym,i64).
: short(sym).
& a queue(queue1,2).
& b queue(queue2,5).
short($x) <- queue($x,$v) & int_le($v,3).
? short(queue1).
? short(queue2).
