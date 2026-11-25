: ownership(sym).
: owner(sym).
& a ownership("caseA").
& b ownership("caseB").
owner($x) <- ownership($x) & sym_eq($x,"caseA").
? owner("caseA").
? owner("caseB").
