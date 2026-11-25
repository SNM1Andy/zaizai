: grocery(sym,qty(cny_cent)).
: within_budget(sym).
& a grocery(week1,700@cny_cent).
& b grocery(week2,1400@cny_cent).
within_budget($x) <- grocery($x,$c) & qty_le($c,1000@cny_cent).
? within_budget(week1).
? within_budget(week2).
