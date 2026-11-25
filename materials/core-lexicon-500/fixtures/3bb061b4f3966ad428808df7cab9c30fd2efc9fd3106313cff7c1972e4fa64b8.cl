: suspect(sym).
: cleared(sym).
& a !suspect(guest1).
!cleared($x) <- !suspect($x).
? cleared(guest1).
? cleared(guest2).
