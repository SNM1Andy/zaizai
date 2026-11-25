: observed(sym).
: inferred(sym).
: concluded(sym).
& a observed(cond1).
inferred($x) <- observed($x).
concluded($x) <- inferred($x).
? concluded(cond1).
? concluded(cond2).
