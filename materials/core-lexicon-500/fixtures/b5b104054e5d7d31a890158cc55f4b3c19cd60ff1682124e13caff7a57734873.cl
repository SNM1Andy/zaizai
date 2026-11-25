: property_fee(sym,qty(cny_cent)).
: small(sym).
& a property_fee(case1,700@cny_cent).
& b property_fee(case2,1400@cny_cent).
small($x) <- property_fee($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
