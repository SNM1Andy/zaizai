: given(sym).
: derived(sym).
: concluded(sym).
& a given(case1).
derived($x) <- given($x).
concluded($x) <- derived($x).
? concluded(case1).
? concluded(case2).
