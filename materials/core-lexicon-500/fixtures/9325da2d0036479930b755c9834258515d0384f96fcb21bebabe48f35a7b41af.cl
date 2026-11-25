: threshold_hit(sym,qty(cny_cent)).
: reached(sym).
& a threshold_hit(case1,700@cny_cent).
& b threshold_hit(case2,1400@cny_cent).
reached($x) <- threshold_hit($x,$c) & qty_le($c,1000@cny_cent).
? reached(case1).
? reached(case2).
