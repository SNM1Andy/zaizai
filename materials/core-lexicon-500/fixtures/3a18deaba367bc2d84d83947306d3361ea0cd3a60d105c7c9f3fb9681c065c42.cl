: fuel(sym,qty(cny_cent)).
: within_budget(sym).
& a fuel(car1,700@cny_cent).
& b fuel(car2,1400@cny_cent).
within_budget($x) <- fuel($x,$c) & qty_le($c,1000@cny_cent).
? within_budget(car1).
? within_budget(car2).
