: baseline(sym,qty(cny_cent)).
: low(sym).
& a baseline(base1,700@cny_cent).
& b baseline(base2,1400@cny_cent).
low($x) <- baseline($x,$c) & qty_le($c,1000@cny_cent).
? low(base1).
? low(base2).
