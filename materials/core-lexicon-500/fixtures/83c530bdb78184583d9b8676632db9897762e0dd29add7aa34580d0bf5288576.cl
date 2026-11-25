: budget_alert(sym,qty(cny_cent)).
: high(sym).
& a budget_alert(case1,700@cny_cent).
& b budget_alert(case2,1400@cny_cent).
high($x) <- budget_alert($x,$c) & qty_le($c,1000@cny_cent).
? high(case1).
? high(case2).
