: endorsed(sym).
: objected(sym).
& a !endorsed("caseA").
!objected($x) <- !endorsed($x).
? objected("caseA").
? objected("caseB").
