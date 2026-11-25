: attempts(sym,i64).
: limited(sym).
& a attempts(device1,2).
& b attempts(device2,5).
limited($x) <- attempts($x,$v) & int_le($v,3).
? limited(device1).
? limited(device2).
