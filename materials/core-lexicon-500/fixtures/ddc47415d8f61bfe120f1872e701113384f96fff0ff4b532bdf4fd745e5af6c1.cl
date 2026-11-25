: dep(sym).
: ready(sym).
& a dep(build1).
ready($x) <- sym_eq($x,build1) & dep($x).
? ready(build1).
