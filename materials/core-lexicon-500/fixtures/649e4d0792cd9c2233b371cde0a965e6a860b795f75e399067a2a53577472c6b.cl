: deviation(sym,i64).
: normal(sym).
& a deviation(dev1,15).
& b deviation(dev2,20).
normal($x) <- deviation($x,$v) & int_le(12,$v) & int_lt($v,18).
? normal(dev1).
? normal(dev2).
