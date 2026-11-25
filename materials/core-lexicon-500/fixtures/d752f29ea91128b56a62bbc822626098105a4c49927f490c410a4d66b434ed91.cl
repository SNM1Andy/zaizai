: traffic_fine(sym,qty(cny_cent)).
: small(sym).
& a traffic_fine(case1,700@cny_cent).
& b traffic_fine(case2,1400@cny_cent).
small($x) <- traffic_fine($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
