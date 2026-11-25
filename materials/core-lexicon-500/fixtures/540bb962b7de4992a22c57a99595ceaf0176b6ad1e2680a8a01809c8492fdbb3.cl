: rule_id(sym).
: target(sym).
& a rule_id("caseA").
& b rule_id("caseB").
target($x) <- rule_id($x) & sym_eq($x,"caseA").
? target("caseA").
? target("caseB").
