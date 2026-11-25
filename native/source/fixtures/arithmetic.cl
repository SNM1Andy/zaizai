: invoice(sym,qty(cny_cent)).
: shipping(sym,qty(cny_cent)).
: bill(sym,qty(cny_cent)).
& base invoice(alpha,5000@cny_cent).
& freight shipping(alpha,1000@cny_cent).
bill($x,$sum) <- invoice($x,$a) & shipping($x,$b) & qty_add($a,$b,$sum).
? bill(alpha,6000@cny_cent).
