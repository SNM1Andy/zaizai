: corroborated(sym,sym).
: confirmed(sym).
& a corroborated(caseA,item).
& b corroborated(caseB,item).
confirmed($x) <- corroborated($x,item).
? confirmed(caseA).
? confirmed(caseB).
