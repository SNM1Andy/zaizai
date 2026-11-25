: delivery(sym,qty(cny_cent)).
: cheap(sym).
& a delivery(noon,45@cny_cent).
& b delivery(night,60@cny_cent).
cheap($x) <- delivery($x,$c) & qty_lt($c,50@cny_cent).
? cheap(noon).
? cheap(night).
