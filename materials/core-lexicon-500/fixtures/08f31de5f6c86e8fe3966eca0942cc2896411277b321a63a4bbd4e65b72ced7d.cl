: cost(sym,qty(cny_cent)).
: within(sym).
& a cost(pilot,700@cny_cent).
& b cost(crew,700@cny_cent).
within($x) <- cost($x,$c) & qty_le($c,1000@cny_cent).
? within(pilot).
? within(crew).
