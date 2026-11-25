: master_slave(sym,i64).
: few(sym).
& a master_slave(case1,2).
& b master_slave(case2,5).
few($x) <- master_slave($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
