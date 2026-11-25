: invoice(sym,qty(cny_cent)).
: small(sym).
& a invoice(case1,700@cny_cent).
& b invoice(case2,1400@cny_cent).
small($x) <- invoice($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
