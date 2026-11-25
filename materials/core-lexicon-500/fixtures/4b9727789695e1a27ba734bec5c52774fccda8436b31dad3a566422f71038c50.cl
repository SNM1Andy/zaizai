: reported(sym).
: inferred(sym).
: concluded(sym).
& a reported(report1).
inferred($x) <- reported($x).
concluded($x) <- inferred($x).
? concluded(report1).
? concluded(report2).
