: repair_wait(sym,i64).
: quick(sym).
& a repair_wait(ticket1,2).
& b repair_wait(ticket2,5).
quick($x) <- repair_wait($x,$v) & int_le($v,3).
? quick(ticket1).
? quick(ticket2).
