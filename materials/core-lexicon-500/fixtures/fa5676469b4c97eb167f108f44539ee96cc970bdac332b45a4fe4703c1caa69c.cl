: trend(sym,i64).
: rising(sym).
& a trend(case1,15).
& b trend(case2,20).
rising($x) <- trend($x,$v) & int_le(12,$v) & int_lt($v,18).
? rising(case1).
? rising(case2).
