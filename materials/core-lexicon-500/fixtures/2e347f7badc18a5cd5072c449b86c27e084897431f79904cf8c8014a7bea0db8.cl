: cost(sym,qty(cny_cent)).
: under_1000(sym).
: under_700(sym).
& a cost(pilot,700@cny_cent).
under_1000($x) <- cost($x,$c) & qty_lt($c,1000@cny_cent).
under_700($x) <- cost($x,$c) & qty_lt($c,700@cny_cent).
? under_1000(pilot).
? under_700(pilot).
