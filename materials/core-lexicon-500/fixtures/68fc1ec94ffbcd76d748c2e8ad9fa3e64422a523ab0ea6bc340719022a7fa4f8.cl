: heard(sym).
: said(sym).
& a heard(ben).
& b heard(cai).
said($x) <- heard($x).
? said(ben).
? said(cai).
