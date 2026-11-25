: found(sym).
: isolated(sym).
: cleared(sym).
& a found(case1).
isolated($x) <- found($x).
cleared($x) <- isolated($x).
? cleared(case1).
? cleared(case2).
