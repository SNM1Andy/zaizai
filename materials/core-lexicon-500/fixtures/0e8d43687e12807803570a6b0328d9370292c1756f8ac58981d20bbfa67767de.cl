: flight(sym,qty(cny_cent)).
: small(sym).
& a flight(case1,700@cny_cent).
& b flight(case2,1400@cny_cent).
small($x) <- flight($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
