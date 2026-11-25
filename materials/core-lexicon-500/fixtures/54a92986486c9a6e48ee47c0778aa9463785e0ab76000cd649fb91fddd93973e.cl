: souvenir(sym,qty(cny_cent)).
: cheap(sym).
& a souvenir(case1,45@cny_cent).
& b souvenir(case2,60@cny_cent).
cheap($x) <- souvenir($x,$c) & qty_lt($c,50@cny_cent).
? cheap(case1).
? cheap(case2).
