: count(sym,i64).
: few(sym).
& a count(set1,2).
& b count(set2,5).
few($x) <- count($x,$v) & int_le($v,3).
? few(set1).
? few(set2).
