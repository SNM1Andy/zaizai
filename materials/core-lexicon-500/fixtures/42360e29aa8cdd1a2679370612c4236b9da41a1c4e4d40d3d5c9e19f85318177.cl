: vendor(sym).
: approved(sym).
& a vendor("caseA").
& b vendor("caseB").
approved($x) <- vendor($x) & sym_eq($x,"caseA").
? approved("caseA").
? approved("caseB").
