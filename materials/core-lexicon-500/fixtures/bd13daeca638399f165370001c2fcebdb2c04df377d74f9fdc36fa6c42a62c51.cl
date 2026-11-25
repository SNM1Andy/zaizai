: confidence_level(sym,i64).
: high(sym).
& a confidence_level(case1,2).
& b confidence_level(case2,5).
high($x) <- confidence_level($x,$v) & int_le($v,3).
? high(case1).
? high(case2).
