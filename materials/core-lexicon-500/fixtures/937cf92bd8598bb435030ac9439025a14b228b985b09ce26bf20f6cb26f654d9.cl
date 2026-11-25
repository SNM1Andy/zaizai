: heating(sym,qty(cny_cent)).
: small(sym).
& a heating(case1,700@cny_cent).
& b heating(case2,1400@cny_cent).
small($x) <- heating($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
