: error_budget(sym,qty(cny_cent)).
: left(sym).
& a error_budget(case1,700@cny_cent).
& b error_budget(case2,1400@cny_cent).
left($x) <- error_budget($x,$c) & qty_le($c,1000@cny_cent).
? left(case1).
? left(case2).
