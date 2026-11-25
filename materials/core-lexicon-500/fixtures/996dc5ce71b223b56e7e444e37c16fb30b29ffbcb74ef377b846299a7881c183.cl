: observed_by(sym,sym).
: included(sym).
& a observed_by(caseA,item).
& b observed_by(caseB,item).
included($x) <- observed_by($x,item).
? included(caseA).
? included(caseB).
