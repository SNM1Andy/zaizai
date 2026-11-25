: quarter(sym,i64).
: first_half(sym).
& a quarter(q1,2).
& b quarter(q5,5).
first_half($x) <- quarter($x,$v) & int_le(1,$v) & int_lt($v,5).
? first_half(q1).
? first_half(q5).
