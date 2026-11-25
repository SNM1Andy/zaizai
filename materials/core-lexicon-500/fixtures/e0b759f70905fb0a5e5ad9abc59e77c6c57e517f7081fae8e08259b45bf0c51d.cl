: reading(sym,i64).
: at_most_42(sym).
: at_most_41(sym).
& a reading(s1,42).
at_most_42($x) <- reading($x,$v) & int_le($v,42).
at_most_41($x) <- reading($x,$v) & int_le($v,41).
? at_most_42(s1).
? at_most_41(s1).
