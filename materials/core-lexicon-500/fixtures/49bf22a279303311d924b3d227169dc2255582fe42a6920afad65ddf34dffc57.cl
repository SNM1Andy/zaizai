: affected(sym).
: propagated(sym).
& a !affected(caseA).
!propagated($x) <- !affected($x).
? propagated(caseA).
? propagated(caseB).
