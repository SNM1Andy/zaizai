: cost(sym,qty(cny_cent)).
: budget(qty(cny_cent)).
: feasible(sym).
& cap budget(10000@cny_cent).
& quote_a cost(alpha,6000@cny_cent).
& quote_b cost(beta,11000@cny_cent).
feasible($x) <- cost($x,$c) & budget($b) & qty_le($c,$b).
!feasible($x) <- cost($x,$c) & budget($b) & qty_lt($b,$c).
? feasible(alpha).
? feasible(beta).
