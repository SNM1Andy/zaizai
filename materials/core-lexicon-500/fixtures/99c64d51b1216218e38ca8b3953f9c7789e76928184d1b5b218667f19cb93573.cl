: name(sym).
: canonical(sym).
& a name(primary).
& b name(secondary).
canonical($x) <- name($x) & sym_eq($x,primary).
? canonical(primary).
? canonical(secondary).
