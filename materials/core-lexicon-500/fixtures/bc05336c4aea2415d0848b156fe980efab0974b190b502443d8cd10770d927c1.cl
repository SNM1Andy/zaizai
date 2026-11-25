: copied_as(sym,sym).
: unique(sym).
& a copied_as(caseA,item).
& b copied_as(caseB,item).
unique($x) <- copied_as($x,item).
? unique(caseA).
? unique(caseB).
