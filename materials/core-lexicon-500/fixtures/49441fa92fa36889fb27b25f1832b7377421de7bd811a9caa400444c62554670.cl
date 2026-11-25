: review_round(sym,i64).
: few(sym).
& a review_round(case1,2).
& b review_round(case2,5).
few($x) <- review_round($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
