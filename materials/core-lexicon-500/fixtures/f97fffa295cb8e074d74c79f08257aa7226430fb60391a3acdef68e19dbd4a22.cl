: size(sym,i64).
: acceptable(sym).
& a size(pkg1,30).
& b size(pkg2,90).
acceptable($x) <- size($x,$v) & int_le($v,60).
? acceptable(pkg1).
? acceptable(pkg2).
