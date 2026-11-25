: variance(sym,i64).
: low(sym).
& a variance(case1,2).
& b variance(case2,5).
low($x) <- variance($x,$v) & int_le($v,3).
? low(case1).
? low(case2).
