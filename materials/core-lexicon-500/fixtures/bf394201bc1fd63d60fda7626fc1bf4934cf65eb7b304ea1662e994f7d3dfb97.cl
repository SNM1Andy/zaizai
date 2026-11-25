: class_fee(sym,qty(cny_cent)).
: small(sym).
& a class_fee(case1,700@cny_cent).
& b class_fee(case2,1400@cny_cent).
small($x) <- class_fee($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
