: witnesses(sym,i64).
: sufficient(sym).
& a witnesses(case1,2).
& b witnesses(case2,5).
sufficient($x) <- witnesses($x,$v) & int_le($v,3).
? sufficient(case1).
? sufficient(case2).
