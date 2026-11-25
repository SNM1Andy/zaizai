: label(sym).
: bare(sym).
& a label("ben").
bare(no) <- label($x) & sym_eq($x,ben).
? bare(no).
