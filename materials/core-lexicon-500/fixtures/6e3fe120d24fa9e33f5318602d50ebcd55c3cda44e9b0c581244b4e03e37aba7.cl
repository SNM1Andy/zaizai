: deadline(sym).
: trusted(sym).
& a deadline(sourceA).
& b deadline(sourceB).
& c !deadline(sourceB).
trusted($x) <- deadline($x).
!trusted($x) <- !deadline($x).
? trusted(sourceB).
? trusted(sourceA).
