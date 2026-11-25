: cycle(sym,i64).
: short_cycle(sym).
& a cycle(batch1,2).
& b cycle(batch2,5).
short_cycle($x) <- cycle($x,$v) & int_le($v,3).
? short_cycle(batch1).
? short_cycle(batch2).
