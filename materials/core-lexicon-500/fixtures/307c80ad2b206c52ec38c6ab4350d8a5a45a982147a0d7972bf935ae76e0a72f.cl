: bill(sym,qty(cny_cent)).
: within_budget(sym).
& a bill(home1,700@cny_cent).
within_budget($x) <- bill($x,$c) & qty_add($c,300@cny_cent,$t) & qty_le($t,1000@cny_cent).
? within_budget(home1).
? within_budget(home2).
