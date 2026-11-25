: evidence(sym).
: assumed(sym).
& a evidence(known).
assumed($x) <- evidence($x).
? assumed(unknown).
? assumed(known).
