: beauty(sym,qty(cny_cent)).
: small(sym).
& a beauty(case1,700@cny_cent).
& b beauty(case2,1400@cny_cent).
small($x) <- beauty($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
