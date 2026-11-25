: car_service(sym,qty(cny_cent)).
: small(sym).
& a car_service(case1,700@cny_cent).
& b car_service(case2,1400@cny_cent).
small($x) <- car_service($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
