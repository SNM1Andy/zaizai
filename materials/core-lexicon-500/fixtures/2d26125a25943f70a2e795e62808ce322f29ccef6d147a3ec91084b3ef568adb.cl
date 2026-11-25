: quorum(sym,i64).
: met(sym).
& a quorum(case1,2).
& b quorum(case2,5).
met($x) <- quorum($x,$v) & int_le($v,3).
? met(case1).
? met(case2).
