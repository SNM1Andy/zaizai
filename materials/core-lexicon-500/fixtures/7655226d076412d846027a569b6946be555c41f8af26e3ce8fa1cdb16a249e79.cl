: copied(sym,sym).
: duplicated(sym).
& a copied("copyA",record1).
& b copied("copyB",record1).
duplicated($x) <- copied($x,record1).
? duplicated("copyA").
? duplicated("copyB").
