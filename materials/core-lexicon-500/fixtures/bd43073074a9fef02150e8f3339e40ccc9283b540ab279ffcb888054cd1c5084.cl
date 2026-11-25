: disk(sym,qty(mib)).
: small(sym).
& a disk(vol1,700@mib).
& b disk(vol2,1400@mib).
small($x) <- disk($x,$c) & qty_le($c,1000@mib).
? small(vol1).
? small(vol2).
