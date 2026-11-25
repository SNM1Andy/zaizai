: membership(sym,qty(cny_cent)).
: small(sym).
& a membership(case1,700@cny_cent).
& b membership(case2,1400@cny_cent).
small($x) <- membership($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
