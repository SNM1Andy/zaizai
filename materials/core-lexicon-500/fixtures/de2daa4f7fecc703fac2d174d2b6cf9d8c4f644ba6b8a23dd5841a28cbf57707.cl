: impact_scope(sym,i64).
: wide(sym).
& a impact_scope(case1,2).
& b impact_scope(case2,5).
wide($x) <- impact_scope($x,$v) & int_le($v,3).
? wide(case1).
? wide(case2).
