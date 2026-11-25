: metro(sym,qty(cny_cent)).
: cheap(sym).
& a metro(case1,45@cny_cent).
& b metro(case2,60@cny_cent).
cheap($x) <- metro($x,$c) & qty_lt($c,50@cny_cent).
? cheap(case1).
? cheap(case2).
