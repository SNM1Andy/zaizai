: batch_count(sym,i64).
: few(sym).
& a batch_count(case1,2).
& b batch_count(case2,5).
few($x) <- batch_count($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
