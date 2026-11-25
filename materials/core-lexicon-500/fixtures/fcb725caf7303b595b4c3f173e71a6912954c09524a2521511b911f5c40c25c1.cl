: package(sym,qty(mib)).
: small(sym).
& a package(package1,700@mib).
& b package(package2,1400@mib).
small($x) <- package($x,$c) & qty_le($c,1000@mib).
? small(package1).
? small(package2).
