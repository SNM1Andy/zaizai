: pet(sym,qty(cny_cent)).
: affordable(sym).
& a pet(cat,700@cny_cent).
& b pet(dog,1400@cny_cent).
affordable($x) <- pet($x,$c) & qty_le($c,1000@cny_cent).
? affordable(cat).
? affordable(dog).
