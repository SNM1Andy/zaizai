: cost_center(sym).
: current(sym).
& a cost_center("caseA").
& b cost_center("caseB").
current($x) <- cost_center($x) & sym_eq($x,"caseA").
? current("caseA").
? current("caseB").
