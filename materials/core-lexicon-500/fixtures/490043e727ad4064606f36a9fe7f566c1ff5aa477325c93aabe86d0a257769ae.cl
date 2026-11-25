: moving(sym,qty(cny_cent)).
: acceptable(sym).
& a moving(move1,700@cny_cent).
& b moving(move2,1400@cny_cent).
acceptable($x) <- moving($x,$c) & qty_le($c,1000@cny_cent).
? acceptable(move1).
? acceptable(move2).
