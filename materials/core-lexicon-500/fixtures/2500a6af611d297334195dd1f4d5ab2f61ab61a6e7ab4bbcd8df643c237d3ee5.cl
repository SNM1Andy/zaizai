: laundry(sym,qty(cny_cent)).
: cheap(sym).
& a laundry(order1,700@cny_cent).
& b laundry(order2,1400@cny_cent).
cheap($x) <- laundry($x,$c) & qty_le($c,1000@cny_cent).
? cheap(order1).
? cheap(order2).
