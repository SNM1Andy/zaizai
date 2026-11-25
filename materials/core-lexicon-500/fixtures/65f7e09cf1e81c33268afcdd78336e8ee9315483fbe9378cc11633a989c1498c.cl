: sufficiency(sym,qty(cny_cent)).
: enough(sym).
& a sufficiency(case1,700@cny_cent).
& b sufficiency(case2,1400@cny_cent).
enough($x) <- sufficiency($x,$c) & qty_le($c,1000@cny_cent).
? enough(case1).
? enough(case2).
