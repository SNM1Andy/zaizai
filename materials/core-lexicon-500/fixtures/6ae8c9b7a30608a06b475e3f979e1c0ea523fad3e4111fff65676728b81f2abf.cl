: show(sym,qty(cny_cent)).
: small(sym).
& a show(case1,700@cny_cent).
& b show(case2,1400@cny_cent).
small($x) <- show($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
