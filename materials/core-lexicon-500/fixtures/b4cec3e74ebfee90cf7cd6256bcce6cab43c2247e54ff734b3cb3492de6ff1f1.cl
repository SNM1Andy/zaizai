: visa(sym,qty(cny_cent)).
: cheap(sym).
& a visa(visa1,700@cny_cent).
& b visa(visa2,1400@cny_cent).
cheap($x) <- visa($x,$c) & qty_le($c,1000@cny_cent).
? cheap(visa1).
? cheap(visa2).
