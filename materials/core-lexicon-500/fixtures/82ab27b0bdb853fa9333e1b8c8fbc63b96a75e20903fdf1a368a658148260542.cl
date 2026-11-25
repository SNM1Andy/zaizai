: detected(sym).
: promoted(sym).
: resumed(sym).
& a detected(case1).
promoted($x) <- detected($x).
resumed($x) <- promoted($x).
? resumed(case1).
? resumed(case2).
