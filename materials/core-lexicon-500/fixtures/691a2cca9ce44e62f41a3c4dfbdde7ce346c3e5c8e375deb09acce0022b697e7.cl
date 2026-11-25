: confirmed(sym).
: rejected(sym).
& a !confirmed(claim1).
!rejected($x) <- !confirmed($x).
? rejected(claim1).
? rejected(claim2).
