: nanny(sym,qty(cny_cent)).
: small(sym).
& a nanny(case1,700@cny_cent).
& b nanny(case2,1400@cny_cent).
small($x) <- nanny($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
