: furniture(sym,qty(cny_cent)).
: small(sym).
& a furniture(case1,700@cny_cent).
& b furniture(case2,1400@cny_cent).
small($x) <- furniture($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
