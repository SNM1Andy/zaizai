: storage(sym,qty(cny_cent)).
: small(sym).
& a storage(case1,700@cny_cent).
& b storage(case2,1400@cny_cent).
small($x) <- storage($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
