: cache(sym,qty(mib)).
: small(sym).
& a cache(case1,700@mib).
& b cache(case2,1400@mib).
small($x) <- cache($x,$c) & qty_le($c,1000@mib).
? small(case1).
? small(case2).
