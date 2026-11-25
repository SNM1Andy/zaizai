: bandwidth(sym,qty(mib)).
: small(sym).
& a bandwidth(link1,700@mib).
& b bandwidth(link2,1400@mib).
small($x) <- bandwidth($x,$c) & qty_le($c,1000@mib).
? small(link1).
? small(link2).
