: corroborating_docs(sym,qty(cny_cent)).
: enough(sym).
& a corroborating_docs(case1,700@cny_cent).
& b corroborating_docs(case2,1400@cny_cent).
enough($x) <- corroborating_docs($x,$c) & qty_le($c,1000@cny_cent).
? enough(case1).
? enough(case2).
