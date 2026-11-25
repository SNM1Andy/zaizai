: optical(sym,qty(cny_cent)).
: small(sym).
& a optical(case1,700@cny_cent).
& b optical(case2,1400@cny_cent).
small($x) <- optical($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
