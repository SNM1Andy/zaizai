: gate(sym,qty(cny_cent)).
: open(sym).
& a gate(case1,700@cny_cent).
& b gate(case2,1400@cny_cent).
open($x) <- gate($x,$c) & qty_le($c,1000@cny_cent).
? open(case1).
? open(case2).
