: guide(sym,qty(cny_cent)).
: small(sym).
& a guide(case1,700@cny_cent).
& b guide(case2,1400@cny_cent).
small($x) <- guide($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
