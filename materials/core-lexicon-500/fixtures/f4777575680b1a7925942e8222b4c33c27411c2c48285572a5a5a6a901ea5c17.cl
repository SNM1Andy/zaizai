: necessity(sym,qty(cny_cent)).
: required(sym).
& a necessity(case1,700@cny_cent).
& b necessity(case2,1400@cny_cent).
required($x) <- necessity($x,$c) & qty_le($c,1000@cny_cent).
? required(case1).
? required(case2).
