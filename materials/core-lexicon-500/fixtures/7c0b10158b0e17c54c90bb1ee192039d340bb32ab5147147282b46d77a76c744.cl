: planned(sym).
: executed(sym).
: reviewed(sym).
& a planned(case1).
executed($x) <- planned($x).
reviewed($x) <- executed($x).
? reviewed(case1).
? reviewed(case2).
