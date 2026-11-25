: cost(sym,qty(cny_cent)).
: within(sym).
& a cost(pilot,700@cny_cent).
within($x) <- cost($x,$cost) & qty_le($cost,1000@cny_cent).
? within(pilot).
