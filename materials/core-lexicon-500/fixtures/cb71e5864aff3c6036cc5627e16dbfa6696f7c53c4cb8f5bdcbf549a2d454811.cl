: tag_policy(sym).
: required(sym).
& a tag_policy("caseA").
& b tag_policy("caseB").
required($x) <- tag_policy($x) & sym_eq($x,"caseA").
? required("caseA").
? required("caseB").
