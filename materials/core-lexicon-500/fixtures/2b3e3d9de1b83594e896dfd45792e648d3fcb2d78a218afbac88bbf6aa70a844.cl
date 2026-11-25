: tuition(sym,qty(cny_cent)).
: within_budget(sym).
& a tuition(term1,7000@cny_cent).
& b tuition(term2,14000@cny_cent).
within_budget($x) <- tuition($x,$c) & qty_le($c,10000@cny_cent).
? within_budget(term1).
? within_budget(term2).
