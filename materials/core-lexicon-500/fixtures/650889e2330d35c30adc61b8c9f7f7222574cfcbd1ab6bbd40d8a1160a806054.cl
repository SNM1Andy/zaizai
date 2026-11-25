: named(sym).
: other(sym).
& a named(one).
other($x) <- sym_ne($x,two) & named($x).
? other(one).
