: vehicle_check(sym,qty(cny_cent)).
: small(sym).
& a vehicle_check(case1,700@cny_cent).
& b vehicle_check(case2,1400@cny_cent).
small($x) <- vehicle_check($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
