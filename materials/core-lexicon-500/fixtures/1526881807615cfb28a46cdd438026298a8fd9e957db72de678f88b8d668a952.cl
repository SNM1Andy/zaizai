: parking(sym,qty(cny_cent)).
: cheap(sym).
& a parking(lot1,45@cny_cent).
& b parking(lot2,60@cny_cent).
cheap($x) <- parking($x,$c) & qty_lt($c,50@cny_cent).
? cheap(lot1).
? cheap(lot2).
