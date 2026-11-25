: evidence_count(sym,i64).
: enough(sym).
& a evidence_count(case1,2).
& b evidence_count(case2,5).
enough($x) <- evidence_count($x,$v) & int_le($v,3).
? enough(case1).
? enough(case2).
