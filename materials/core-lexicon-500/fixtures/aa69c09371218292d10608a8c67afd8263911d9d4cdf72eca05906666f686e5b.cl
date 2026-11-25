: log(sym,qty(mib)).
: small(sym).
& a log(case1,700@mib).
& b log(case2,1400@mib).
small($x) <- log($x,$c) & qty_le($c,1000@mib).
? small(case1).
? small(case2).
