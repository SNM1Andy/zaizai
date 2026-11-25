: alias(sym).
: canonical(sym).
& a alias(caseA).
& b alias(caseB).
canonical($x) <- alias($x) & sym_eq($x,caseA).
? canonical(caseA).
? canonical(caseB).
