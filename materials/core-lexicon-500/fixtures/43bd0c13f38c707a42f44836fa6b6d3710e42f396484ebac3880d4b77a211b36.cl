: tip(sym,qty(cny_cent)).
: cheap(sym).
& a tip(case1,45@cny_cent).
& b tip(case2,60@cny_cent).
cheap($x) <- tip($x,$c) & qty_lt($c,50@cny_cent).
? cheap(case1).
? cheap(case2).
