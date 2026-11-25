: measure(sym,qty(cny_cent)).
: above(sym).
& a measure(m1,700@cny_cent).
& b measure(m2,1400@cny_cent).
above($x) <- measure($x,$c) & qty_le($c,1000@cny_cent).
? above(m1).
? above(m2).
