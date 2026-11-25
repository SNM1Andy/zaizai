: size(sym,qty(mib)).
: compare(sym).
& a size(pkg1,700@mib).
compare($x) <- size($x,$c) & qty_le($c,1@gib).
? compare(pkg1).
