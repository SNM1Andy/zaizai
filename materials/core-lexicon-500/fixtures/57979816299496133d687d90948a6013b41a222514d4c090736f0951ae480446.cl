: baseline_value(sym,qty(cny_cent)).
: low(sym).
& a baseline_value(case1,700@cny_cent).
& b baseline_value(case2,1400@cny_cent).
low($x) <- baseline_value($x,$c) & qty_le($c,1000@cny_cent).
? low(case1).
? low(case2).
