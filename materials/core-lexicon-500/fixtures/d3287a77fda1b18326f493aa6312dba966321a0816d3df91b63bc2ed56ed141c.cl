: courier(sym,qty(cny_cent)).
: cheap(sym).
& a courier(case1,45@cny_cent).
& b courier(case2,60@cny_cent).
cheap($x) <- courier($x,$c) & qty_lt($c,50@cny_cent).
? cheap(case1).
? cheap(case2).
