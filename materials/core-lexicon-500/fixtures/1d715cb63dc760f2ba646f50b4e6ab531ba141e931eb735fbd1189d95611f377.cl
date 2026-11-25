: wedding(sym,qty(cny_cent)).
: small(sym).
& a wedding(case1,700@cny_cent).
& b wedding(case2,1400@cny_cent).
small($x) <- wedding($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
