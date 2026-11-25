: shelf_life(sym,i64).
: few(sym).
& a shelf_life(case1,2).
& b shelf_life(case2,5).
few($x) <- shelf_life($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
