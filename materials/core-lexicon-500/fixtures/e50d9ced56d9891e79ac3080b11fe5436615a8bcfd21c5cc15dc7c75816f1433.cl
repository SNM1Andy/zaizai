: homestay(sym,qty(cny_cent)).
: small(sym).
& a homestay(case1,700@cny_cent).
& b homestay(case2,1400@cny_cent).
small($x) <- homestay($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
