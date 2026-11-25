: rent(sym,qty(cny_cent)).
: affordable(sym).
& a rent(flat1,2800@cny_cent).
& b rent(flat2,4200@cny_cent).
affordable($x) <- rent($x,$c) & qty_le($c,3500@cny_cent).
? affordable(flat1).
? affordable(flat2).
