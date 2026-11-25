: chargeback(sym,qty(cny_cent)).
: small(sym).
& a chargeback(case1,700@cny_cent).
& b chargeback(case2,1400@cny_cent).
small($x) <- chargeback($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
