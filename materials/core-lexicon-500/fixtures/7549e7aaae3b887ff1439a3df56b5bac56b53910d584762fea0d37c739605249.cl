: maternity(sym,qty(cny_cent)).
: small(sym).
& a maternity(case1,700@cny_cent).
& b maternity(case2,1400@cny_cent).
small($x) <- maternity($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
