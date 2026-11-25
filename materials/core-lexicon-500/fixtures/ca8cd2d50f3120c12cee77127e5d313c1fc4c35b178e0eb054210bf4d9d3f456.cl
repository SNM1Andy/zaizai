: index(sym,qty(mib)).
: small(sym).
& a index(case1,700@mib).
& b index(case2,1400@mib).
small($x) <- index($x,$c) & qty_le($c,1000@mib).
? small(case1).
? small(case2).
