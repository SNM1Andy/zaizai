: waste_fee(sym,qty(cny_cent)).
: cheap(sym).
& a waste_fee(case1,45@cny_cent).
& b waste_fee(case2,60@cny_cent).
cheap($x) <- waste_fee($x,$c) & qty_lt($c,50@cny_cent).
? cheap(case1).
? cheap(case2).
