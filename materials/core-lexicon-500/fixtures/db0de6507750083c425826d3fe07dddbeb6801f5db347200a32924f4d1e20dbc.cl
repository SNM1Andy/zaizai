: medical(sym,qty(cny_cent)).
: covered(sym).
& a medical(visit1,700@cny_cent).
& b medical(visit2,1400@cny_cent).
covered($x) <- medical($x,$c) & qty_le($c,1000@cny_cent).
? covered(visit1).
? covered(visit2).
