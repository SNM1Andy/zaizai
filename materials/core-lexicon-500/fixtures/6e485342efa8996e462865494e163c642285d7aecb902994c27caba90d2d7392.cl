: reading(sym,i64).
: below(sym).
& a reading(s1,42).
below($x) <- reading($x,$v) & int_lt($v,50).
? below(s1).
