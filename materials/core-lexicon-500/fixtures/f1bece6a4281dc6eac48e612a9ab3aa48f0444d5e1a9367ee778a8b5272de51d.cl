: swim(sym,qty(cny_cent)).
: cheap(sym).
& a swim(case1,45@cny_cent).
& b swim(case2,60@cny_cent).
cheap($x) <- swim($x,$c) & qty_lt($c,50@cny_cent).
? cheap(case1).
? cheap(case2).
