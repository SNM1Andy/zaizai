: donation(sym,qty(cny_cent)).
: small(sym).
& a donation(case1,700@cny_cent).
& b donation(case2,1400@cny_cent).
small($x) <- donation($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
