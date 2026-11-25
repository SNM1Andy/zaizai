: support(sym,qty(cny_cent)).
: enough(sym).
& a support(caseA,700@cny_cent).
& b support(caseB,1400@cny_cent).
enough($x) <- support($x,$c) & qty_le($c,1000@cny_cent).
? enough(caseA).
? enough(caseB).
