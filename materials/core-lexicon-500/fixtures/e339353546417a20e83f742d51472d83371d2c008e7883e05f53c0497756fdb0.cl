: artifact(sym,qty(mib)).
: small(sym).
& a artifact(artifact1,700@mib).
& b artifact(artifact2,1400@mib).
small($x) <- artifact($x,$c) & qty_le($c,1000@mib).
? small(artifact1).
? small(artifact2).
