: cert(sym,qty(day)).
: short(sym).
& a cert(cert1,3@day).
& b cert(cert2,9@day).
short($x) <- cert($x,$c) & qty_le($c,5@day).
? short(cert1).
? short(cert2).
