: car_rental(sym,qty(cny_cent)).
: small(sym).
& a car_rental(case1,700@cny_cent).
& b car_rental(case2,1400@cny_cent).
small($x) <- car_rental($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
