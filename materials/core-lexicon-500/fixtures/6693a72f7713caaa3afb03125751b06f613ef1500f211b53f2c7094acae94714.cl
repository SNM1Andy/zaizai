: built(sym).
: staged(sym).
: promoted(sym).
& a built(case1).
staged($x) <- built($x).
promoted($x) <- staged($x).
? promoted(case1).
? promoted(case2).
