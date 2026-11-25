: funeral(sym,qty(cny_cent)).
: small(sym).
& a funeral(case1,700@cny_cent).
& b funeral(case2,1400@cny_cent).
small($x) <- funeral($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
