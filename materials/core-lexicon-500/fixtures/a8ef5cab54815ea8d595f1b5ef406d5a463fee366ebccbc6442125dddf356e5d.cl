: sealed(sym).
: stored(sym).
: restorable(sym).
& a sealed(case1).
stored($x) <- sealed($x).
restorable($x) <- stored($x).
? restorable(case1).
? restorable(case2).
