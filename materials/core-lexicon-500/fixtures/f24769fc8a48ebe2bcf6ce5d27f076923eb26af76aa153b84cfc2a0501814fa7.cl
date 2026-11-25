: voted(sym,sym).
: passed(sym).
& a voted("caseA",item).
& b voted("caseB",item).
passed($x) <- voted($x,item).
? passed("caseA").
? passed("caseB").
