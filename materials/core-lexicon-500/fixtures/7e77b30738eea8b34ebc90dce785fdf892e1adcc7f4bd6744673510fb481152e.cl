: cost(sym,qty(cny_cent)).
: limit(sym,qty(cny_cent)).
: checked(sym).
& a cost(pilot,700@cny_cent).
& b limit(pilot,999@cny_cent).
checked($x) <- cost($x,$c) & limit($x,$t) & qty_add($c,300@cny_cent,$t).
? checked(pilot).
