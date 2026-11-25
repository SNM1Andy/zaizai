: hour(sym,i64).
: in_office(sym).
& a hour(t1,10).
& b hour(t2,20).
in_office($x) <- hour($x,$v) & int_le(9,$v) & int_lt($v,18).
? in_office(t1).
? in_office(t2).
