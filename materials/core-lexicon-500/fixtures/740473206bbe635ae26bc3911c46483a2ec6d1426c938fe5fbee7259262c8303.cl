: claimed(sym).
: holds(sym).
& a claimed("claimA").
& b claimed("claimB").
& c !claimed("claimB").
holds($x) <- claimed($x).
!holds($x) <- !claimed($x).
? holds("claimB").
? holds("claimA").
