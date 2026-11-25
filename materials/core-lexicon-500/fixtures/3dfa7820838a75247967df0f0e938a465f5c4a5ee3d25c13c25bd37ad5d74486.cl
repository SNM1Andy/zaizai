: quota(sym,qty(mib)).
: small(sym).
& a quota(ns1,700@mib).
& b quota(ns2,1400@mib).
small($x) <- quota($x,$c) & qty_le($c,1000@mib).
? small(ns1).
? small(ns2).
