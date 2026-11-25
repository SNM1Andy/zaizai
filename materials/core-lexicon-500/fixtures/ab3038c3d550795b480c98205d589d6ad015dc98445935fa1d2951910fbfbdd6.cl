: budget(sym,qty(cny_cent)).
: remaining(sym).
& a budget(proj1,1000@cny_cent).
remaining($x) <- budget($x,$b) & qty_sub($b,300@cny_cent,$v) & qty_le($v,700@cny_cent) & qty_le(700@cny_cent,$v).
? remaining(proj1).
? remaining(proj2).
