: renovation(sym,qty(cny_cent)).
: small(sym).
& a renovation(case1,700@cny_cent).
& b renovation(case2,1400@cny_cent).
small($x) <- renovation($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
