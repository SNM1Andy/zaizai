: fitness(sym,qty(cny_cent)).
: affordable(sym).
& a fitness(gym1,700@cny_cent).
& b fitness(gym2,1400@cny_cent).
affordable($x) <- fitness($x,$c) & qty_le($c,1000@cny_cent).
? affordable(gym1).
? affordable(gym2).
