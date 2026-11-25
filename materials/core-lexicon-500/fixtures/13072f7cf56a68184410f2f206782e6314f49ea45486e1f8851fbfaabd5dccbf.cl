: evidence(sym,qty(cny_cent)).
: strong(sym).
& a evidence(ev1,700@cny_cent).
& b evidence(ev2,1400@cny_cent).
strong($x) <- evidence($x,$c) & qty_le($c,1000@cny_cent).
? strong(ev1).
? strong(ev2).
