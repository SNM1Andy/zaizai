: bus(sym,qty(cny_cent)).
: cheap(sym).
& a bus(case1,45@cny_cent).
& b bus(case2,60@cny_cent).
cheap($x) <- bus($x,$c) & qty_lt($c,50@cny_cent).
? cheap(case1).
? cheap(case2).
