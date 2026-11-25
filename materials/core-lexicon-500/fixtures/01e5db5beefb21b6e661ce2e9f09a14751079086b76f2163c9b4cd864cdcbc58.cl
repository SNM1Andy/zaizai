: birthday(sym,qty(cny_cent)).
: small(sym).
& a birthday(case1,700@cny_cent).
& b birthday(case2,1400@cny_cent).
small($x) <- birthday($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
