: appliance(sym,qty(cny_cent)).
: small(sym).
& a appliance(case1,700@cny_cent).
& b appliance(case2,1400@cny_cent).
small($x) <- appliance($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
