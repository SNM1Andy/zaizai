: cost(sym,qty(cny_cent)).
: same(sym).
& a cost(pilot,700@cny_cent).
same($x) <- cost($x,$c) & qty_le($c,700@usd_cent).
? same(pilot).
