: round_count(sym,i64).
: few(sym).
& a round_count(case1,2).
& b round_count(case2,5).
few($x) <- round_count($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
