: named(sym).
: other(sym).
& a named(one).
other($x) <- named($x) & sym_ne($x,two).
? other(one).
