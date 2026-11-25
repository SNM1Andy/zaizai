: tv_fee(sym,qty(cny_cent)).
: cheap(sym).
& a tv_fee(case1,45@cny_cent).
& b tv_fee(case2,60@cny_cent).
cheap($x) <- tv_fee($x,$c) & qty_lt($c,50@cny_cent).
? cheap(case1).
? cheap(case2).
