: topic(sym,i64).
: few(sym).
& a topic(case1,2).
& b topic(case2,5).
few($x) <- topic($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
