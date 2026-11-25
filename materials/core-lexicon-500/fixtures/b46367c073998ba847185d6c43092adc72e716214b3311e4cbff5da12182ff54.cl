: travel(sym,qty(cny_cent)).
: within_budget(sym).
& a travel(trip1,700@cny_cent).
& b travel(trip2,1400@cny_cent).
within_budget($x) <- travel($x,$c) & qty_le($c,1000@cny_cent).
? within_budget(trip1).
? within_budget(trip2).
