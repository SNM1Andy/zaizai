: testified(sym).
: credible(sym).
& a testified(caseA).
& b testified(caseB).
& c !testified(caseB).
credible($x) <- testified($x).
!credible($x) <- !testified($x).
? credible(caseB).
? credible(caseA).
