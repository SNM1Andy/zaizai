: collected(sym).
: analyzed(sym).
: concluded(sym).
& a collected(case1).
analyzed($x) <- collected($x).
concluded($x) <- analyzed($x).
? concluded(case1).
? concluded(case2).
