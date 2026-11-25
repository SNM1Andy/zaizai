: claimed(sym).
: holds(sym).
& a claimed(claimX).
& b claimed(claimY).
& c !claimed(claimY).
holds($x) <- claimed($x).
!holds($x) <- !claimed($x).
? holds(claimY).
? holds(claimX).
