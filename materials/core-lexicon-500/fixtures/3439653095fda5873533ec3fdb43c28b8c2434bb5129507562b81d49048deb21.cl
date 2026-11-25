: medicine(sym,qty(cny_cent)).
: small(sym).
& a medicine(case1,700@cny_cent).
& b medicine(case2,1400@cny_cent).
small($x) <- medicine($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
