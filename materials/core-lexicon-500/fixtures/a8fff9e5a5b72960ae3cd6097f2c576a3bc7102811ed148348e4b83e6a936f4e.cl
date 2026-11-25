: packaging(sym,qty(cny_cent)).
: cheap(sym).
& a packaging(case1,45@cny_cent).
& b packaging(case2,60@cny_cent).
cheap($x) <- packaging($x,$c) & qty_lt($c,50@cny_cent).
? cheap(case1).
? cheap(case2).
