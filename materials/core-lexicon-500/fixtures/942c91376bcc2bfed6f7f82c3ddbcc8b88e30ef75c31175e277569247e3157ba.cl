: gift(sym,qty(cny_cent)).
: modest(sym).
& a gift(wedding1,700@cny_cent).
& b gift(wedding2,1400@cny_cent).
modest($x) <- gift($x,$c) & qty_le($c,1000@cny_cent).
? modest(wedding1).
? modest(wedding2).
