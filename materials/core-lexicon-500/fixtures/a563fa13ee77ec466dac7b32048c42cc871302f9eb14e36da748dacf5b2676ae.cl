: rail(sym,qty(cny_cent)).
: small(sym).
& a rail(case1,700@cny_cent).
& b rail(case2,1400@cny_cent).
small($x) <- rail($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
