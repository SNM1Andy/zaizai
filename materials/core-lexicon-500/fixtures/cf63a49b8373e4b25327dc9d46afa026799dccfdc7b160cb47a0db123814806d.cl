: compliance(sym,i64).
: good(sym).
& a compliance(case1,15).
& b compliance(case2,20).
good($x) <- compliance($x,$v) & int_le(12,$v) & int_lt($v,18).
? good(case1).
? good(case2).
