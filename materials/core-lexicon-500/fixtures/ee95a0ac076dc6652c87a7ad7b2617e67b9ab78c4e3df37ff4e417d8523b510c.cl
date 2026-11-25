: shard(sym,i64).
: few(sym).
& a shard(case1,2).
& b shard(case2,5).
few($x) <- shard($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
