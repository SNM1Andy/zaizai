: cost(sym,qty(cny_cent)).
: limit(sym,qty(cny_cent)).
: summed(sym).
: checked(sym).
& a cost(pilot,700@cny_cent).
& b limit(pilot,1000@cny_cent).
summed($x) <- cost($x,$c) & qty_add($c,300@cny_cent,$t) & qty_le($t,1000@cny_cent) & qty_le(1000@cny_cent,$t).
checked($x) <- cost($x,$c) & limit($x,$t) & qty_add($c,300@cny_cent,$t).
? summed(pilot).
? checked(pilot).
