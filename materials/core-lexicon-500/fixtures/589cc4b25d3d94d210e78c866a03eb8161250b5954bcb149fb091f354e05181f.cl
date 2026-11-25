: identified(sym).
: tested(sym).
: applied(sym).
& a identified(case1).
tested($x) <- identified($x).
applied($x) <- tested($x).
? applied(case1).
? applied(case2).
