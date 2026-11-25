: repair(sym,qty(cny_cent)).
: acceptable(sym).
& a repair(fix1,700@cny_cent).
& b repair(fix2,1400@cny_cent).
acceptable($x) <- repair($x,$c) & qty_le($c,1000@cny_cent).
? acceptable(fix1).
? acceptable(fix2).
