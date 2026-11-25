: school_bus(sym,qty(cny_cent)).
: small(sym).
& a school_bus(case1,700@cny_cent).
& b school_bus(case2,1400@cny_cent).
small($x) <- school_bus($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
