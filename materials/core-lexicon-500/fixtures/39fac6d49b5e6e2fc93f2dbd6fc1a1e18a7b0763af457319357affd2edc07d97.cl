: luggage(sym,qty(cny_cent)).
: cheap(sym).
& a luggage(case1,45@cny_cent).
& b luggage(case2,60@cny_cent).
cheap($x) <- luggage($x,$c) & qty_lt($c,50@cny_cent).
? cheap(case1).
? cheap(case2).
