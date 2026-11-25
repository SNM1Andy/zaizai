: throughput(sym,qty(mib)).
: small(sym).
& a throughput(case1,700@mib).
& b throughput(case2,1400@mib).
small($x) <- throughput($x,$c) & qty_le($c,1000@mib).
? small(case1).
? small(case2).
