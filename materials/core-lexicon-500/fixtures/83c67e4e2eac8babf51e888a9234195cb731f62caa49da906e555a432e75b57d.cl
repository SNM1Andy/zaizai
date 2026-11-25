: dental(sym,qty(cny_cent)).
: small(sym).
& a dental(case1,700@cny_cent).
& b dental(case2,1400@cny_cent).
small($x) <- dental($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
