: massage(sym,qty(cny_cent)).
: small(sym).
& a massage(case1,700@cny_cent).
& b massage(case2,1400@cny_cent).
small($x) <- massage($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
