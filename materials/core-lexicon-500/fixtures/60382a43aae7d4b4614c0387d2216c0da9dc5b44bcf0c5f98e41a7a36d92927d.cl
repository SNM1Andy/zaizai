: driving(sym,qty(cny_cent)).
: small(sym).
& a driving(case1,700@cny_cent).
& b driving(case2,1400@cny_cent).
small($x) <- driving($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
