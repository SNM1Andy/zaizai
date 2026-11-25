: feature_flag(sym).
: enabled(sym).
& a feature_flag("caseA").
& b feature_flag("caseB").
enabled($x) <- feature_flag($x) & sym_eq($x,"caseA").
? enabled("caseA").
? enabled("caseB").
