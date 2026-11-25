: exception(sym).
: special(sym).
& a exception(caseA).
& b exception(caseB).
special($x) <- exception($x) & sym_ne($x,caseB).
? special(caseA).
? special(caseB).
