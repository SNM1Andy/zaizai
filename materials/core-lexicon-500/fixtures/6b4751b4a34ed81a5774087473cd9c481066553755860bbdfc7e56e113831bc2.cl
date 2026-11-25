: observed(sym).
: inferred(sym).
: concluded(sym).
& a observed(item1).
inferred($x) <- observed($x).
concluded($x) <- inferred($x).
? concluded(item1).
? concluded(item2).
