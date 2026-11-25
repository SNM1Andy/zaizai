: week_count(sym,i64).
: few(sym).
& a week_count(case1,2).
& b week_count(case2,5).
few($x) <- week_count($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
