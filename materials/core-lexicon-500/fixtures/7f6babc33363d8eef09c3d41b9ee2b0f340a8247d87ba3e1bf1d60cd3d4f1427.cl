: deposit(sym,qty(cny_cent)).
: acceptable(sym).
& a deposit(lease1,1500@cny_cent).
& b deposit(lease2,2500@cny_cent).
acceptable($x) <- deposit($x,$c) & qty_le($c,2000@cny_cent).
? acceptable(lease1).
? acceptable(lease2).
