: premise(sym).
: derived(sym).
: concluded(sym).
& a premise(case1).
derived($x) <- premise($x).
concluded($x) <- derived($x).
? concluded(case1).
? concluded(case2).
