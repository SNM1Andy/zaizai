: version(sym).
: current(sym).
& a version(v2).
& b version(v1).
current($x) <- version($x) & sym_eq($x,v2).
? current(v2).
? current(v1).
