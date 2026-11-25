: meal(sym,qty(cny_cent)).
: affordable(sym).
& a meal(lunch,45@cny_cent).
& b meal(dinner,60@cny_cent).
affordable($x) <- meal($x,$c) & qty_lt($c,50@cny_cent).
? affordable(lunch).
? affordable(dinner).
