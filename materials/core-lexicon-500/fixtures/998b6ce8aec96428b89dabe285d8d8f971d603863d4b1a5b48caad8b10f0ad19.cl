: testified(sym).
: credible(sym).
& a testified(witnessA).
& b testified(witnessB).
& c !testified(witnessB).
credible($x) <- testified($x).
!credible($x) <- !testified($x).
? credible(witnessB).
? credible(witnessA).
