: size(sym,qty(mib)).
: compare(sym).
& a size(pkg1,700@mib).
compare($x) <- size($x,$s) & qty_le($s,1@mib).
? compare(pkg1).
