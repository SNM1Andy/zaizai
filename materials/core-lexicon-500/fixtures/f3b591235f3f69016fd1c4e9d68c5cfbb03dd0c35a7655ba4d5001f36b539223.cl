: deadline_eng(sym,i64).
: early(sym).
& a deadline_eng(case1,2).
& b deadline_eng(case2,5).
early($x) <- deadline_eng($x,$v) & int_le($v,3).
? early(case1).
? early(case2).
