: clock(sym).
: trusted(sym).
& a clock(clockA).
& b clock(clockB).
& c !clock(clockB).
trusted($x) <- clock($x).
!trusted($x) <- !clock($x).
? trusted(clockB).
? trusted(clockA).
