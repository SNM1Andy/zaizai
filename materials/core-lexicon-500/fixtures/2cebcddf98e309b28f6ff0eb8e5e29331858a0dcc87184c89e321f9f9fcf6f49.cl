: requested(sym).
: approved(sym).
: taken(sym).
& a requested(case1).
approved($x) <- requested($x).
taken($x) <- approved($x).
? taken(case1).
? taken(case2).
