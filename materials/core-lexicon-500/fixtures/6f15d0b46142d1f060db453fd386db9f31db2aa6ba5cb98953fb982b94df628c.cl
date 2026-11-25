: allowed_name(sym).
: allowed(sym).
& a allowed_name("caseA").
& b allowed_name("caseB").
allowed($x) <- allowed_name($x) & sym_eq($x,"caseA").
? allowed("caseA").
? allowed("caseB").
