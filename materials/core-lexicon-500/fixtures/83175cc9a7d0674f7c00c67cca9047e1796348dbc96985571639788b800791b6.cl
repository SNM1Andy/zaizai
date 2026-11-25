: requested(sym).
: granted(sym).
: applied(sym).
& a requested(case1).
granted($x) <- requested($x).
applied($x) <- granted($x).
? applied(case1).
? applied(case2).
