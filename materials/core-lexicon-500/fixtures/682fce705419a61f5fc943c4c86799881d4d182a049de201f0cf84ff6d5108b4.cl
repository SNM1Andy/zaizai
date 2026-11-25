: declared_value(sym,qty(cny_cent)).
: cheap(sym).
& a declared_value(case1,45@cny_cent).
& b declared_value(case2,60@cny_cent).
cheap($x) <- declared_value($x,$c) & qty_lt($c,50@cny_cent).
? cheap(case1).
? cheap(case2).
