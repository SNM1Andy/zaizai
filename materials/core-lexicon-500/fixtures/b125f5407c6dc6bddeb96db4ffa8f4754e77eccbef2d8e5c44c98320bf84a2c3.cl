: config(sym).
: expected(sym).
& a config("caseA").
& b config("caseB").
expected($x) <- config($x) & sym_eq($x,"caseA").
? expected("caseA").
? expected("caseB").
