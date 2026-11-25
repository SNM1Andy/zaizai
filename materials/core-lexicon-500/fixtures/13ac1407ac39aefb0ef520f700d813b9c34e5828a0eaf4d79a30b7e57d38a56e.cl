: capacity(sym,qty(mib)).
: small(sym).
& a capacity(case1,700@mib).
& b capacity(case2,1400@mib).
small($x) <- capacity($x,$c) & qty_le($c,1000@mib).
? small(case1).
? small(case2).
