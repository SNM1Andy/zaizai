: shift(sym,i64).
: early(sym).
& a shift(case1,2).
& b shift(case2,5).
early($x) <- shift($x,$v) & int_le($v,3).
? early(case1).
? early(case2).
