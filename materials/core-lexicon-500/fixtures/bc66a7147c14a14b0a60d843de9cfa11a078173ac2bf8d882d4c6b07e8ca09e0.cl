: fine(sym,qty(cny_cent)).
: small(sym).
& a fine(case1,700@cny_cent).
& b fine(case2,1400@cny_cent).
small($x) <- fine($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
