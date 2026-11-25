: tax(sym,qty(cny_cent)).
: small(sym).
& a tax(case1,700@cny_cent).
& b tax(case2,1400@cny_cent).
small($x) <- tax($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
