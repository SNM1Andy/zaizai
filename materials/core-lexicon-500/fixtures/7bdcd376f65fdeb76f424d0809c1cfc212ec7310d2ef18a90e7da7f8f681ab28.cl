: case_id(sym).
: target(sym).
& a case_id("caseA").
& b case_id("caseB").
target($x) <- case_id($x) & sym_eq($x,"caseA").
? target("caseA").
? target("caseB").
