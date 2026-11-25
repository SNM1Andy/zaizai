: image(sym,qty(mib)).
: small(sym).
& a image(case1,700@mib).
& b image(case2,1400@mib).
small($x) <- image($x,$c) & qty_le($c,1000@mib).
? small(case1).
? small(case2).
