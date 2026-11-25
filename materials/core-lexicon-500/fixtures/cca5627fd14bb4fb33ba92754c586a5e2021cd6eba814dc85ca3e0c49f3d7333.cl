: toll(sym,qty(cny_cent)).
: small(sym).
& a toll(case1,700@cny_cent).
& b toll(case2,1400@cny_cent).
small($x) <- toll($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
