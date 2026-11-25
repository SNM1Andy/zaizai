: dep(sym).
: ready(sym).
& a dep(build1).
ready($x) <- dep($x) & sym_eq($x,build1).
? ready(build1).
