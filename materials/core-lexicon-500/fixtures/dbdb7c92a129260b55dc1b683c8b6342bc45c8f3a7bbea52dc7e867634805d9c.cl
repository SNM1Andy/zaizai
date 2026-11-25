: clothing(sym,qty(cny_cent)).
: within_budget(sym).
& a clothing(season1,700@cny_cent).
& b clothing(season2,1400@cny_cent).
within_budget($x) <- clothing($x,$c) & qty_le($c,1000@cny_cent).
? within_budget(season1).
? within_budget(season2).
