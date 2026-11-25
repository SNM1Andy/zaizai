: asserted(sym).
: consistent(sym).
& a asserted("sourceA").
& b asserted("sourceB").
& c !asserted("sourceB").
consistent($x) <- asserted($x).
!consistent($x) <- !asserted($x).
? consistent("sourceB").
? consistent("sourceA").
