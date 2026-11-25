: game(sym,qty(cny_cent)).
: cheap(sym).
& a game(case1,45@cny_cent).
& b game(case2,60@cny_cent).
cheap($x) <- game($x,$c) & qty_lt($c,50@cny_cent).
? cheap(case1).
? cheap(case2).
