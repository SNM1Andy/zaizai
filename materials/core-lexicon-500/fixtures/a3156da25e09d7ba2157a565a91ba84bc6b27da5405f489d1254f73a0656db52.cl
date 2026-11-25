: requested(sym).
: approved(sym).
: frozen(sym).
& a requested(case1).
approved($x) <- requested($x).
frozen($x) <- approved($x).
? frozen(case1).
? frozen(case2).
