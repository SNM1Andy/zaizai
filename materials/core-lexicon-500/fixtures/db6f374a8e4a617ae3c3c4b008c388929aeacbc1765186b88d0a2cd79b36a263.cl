: attempts(sym,i64).
: within_limit(sym).
& a attempts(device1,2).
& b attempts(device2,5).
within_limit($x) <- attempts($x,$v) & int_le($v,3).
? within_limit(device1).
? within_limit(device2).
