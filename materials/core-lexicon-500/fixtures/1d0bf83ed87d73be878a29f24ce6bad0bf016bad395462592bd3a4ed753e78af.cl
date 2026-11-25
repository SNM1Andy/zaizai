: car_insurance(sym,qty(cny_cent)).
: small(sym).
& a car_insurance(case1,700@cny_cent).
& b car_insurance(case2,1400@cny_cent).
small($x) <- car_insurance($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
