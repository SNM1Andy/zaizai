: reading(sym,i64).
: below_43(sym).
: below_42(sym).
& a reading(s1,42).
below_43($x) <- reading($x,$v) & int_lt($v,43).
below_42($x) <- reading($x,$v) & int_lt($v,42).
? below_43(s1).
? below_42(s1).
