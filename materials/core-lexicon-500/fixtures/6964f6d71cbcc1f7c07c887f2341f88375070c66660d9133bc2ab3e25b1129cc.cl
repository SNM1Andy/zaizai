: domain_name(sym).
: expected(sym).
& a domain_name(caseA).
& b domain_name(caseB).
expected($x) <- domain_name($x) & sym_eq($x,caseA).
? expected(caseA).
? expected(caseB).
