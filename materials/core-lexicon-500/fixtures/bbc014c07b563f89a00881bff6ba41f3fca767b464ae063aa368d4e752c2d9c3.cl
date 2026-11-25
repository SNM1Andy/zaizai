: fare(sym,qty(cny_cent)).
: within_policy(sym).
& a fare(ride1,700@cny_cent).
& b fare(ride2,1400@cny_cent).
within_policy($x) <- fare($x,$c) & qty_le($c,1000@cny_cent).
? within_policy(ride1).
? within_policy(ride2).
