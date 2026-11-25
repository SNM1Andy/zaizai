: vaccine(sym,qty(cny_cent)).
: small(sym).
& a vaccine(case1,700@cny_cent).
& b vaccine(case2,1400@cny_cent).
small($x) <- vaccine($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
