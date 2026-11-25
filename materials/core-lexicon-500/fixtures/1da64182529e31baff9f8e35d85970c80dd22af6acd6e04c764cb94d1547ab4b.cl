: tolerance(sym,i64).
: loose(sym).
& a tolerance(case1,15).
& b tolerance(case2,20).
loose($x) <- tolerance($x,$v) & int_le(12,$v) & int_lt($v,18).
? loose(case1).
? loose(case2).
