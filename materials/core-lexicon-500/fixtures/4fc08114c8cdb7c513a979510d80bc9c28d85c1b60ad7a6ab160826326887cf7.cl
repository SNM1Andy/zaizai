: cutoff(sym,qty(cny_cent)).
: low(sym).
& a cutoff(case1,700@cny_cent).
& b cutoff(case2,1400@cny_cent).
low($x) <- cutoff($x,$c) & qty_le($c,1000@cny_cent).
? low(case1).
? low(case2).
