: taxi(sym,qty(cny_cent)).
: small(sym).
& a taxi(case1,700@cny_cent).
& b taxi(case2,1400@cny_cent).
small($x) <- taxi($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
