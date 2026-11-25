: childcare(sym,qty(cny_cent)).
: affordable(sym).
& a childcare(family1,700@cny_cent).
& b childcare(family2,1400@cny_cent).
affordable($x) <- childcare($x,$c) & qty_le($c,1000@cny_cent).
? affordable(family1).
? affordable(family2).
