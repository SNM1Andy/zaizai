: registry(sym,qty(mib)).
: small(sym).
& a registry(case1,700@mib).
& b registry(case2,1400@mib).
small($x) <- registry($x,$c) & qty_le($c,1000@mib).
? small(case1).
? small(case2).
