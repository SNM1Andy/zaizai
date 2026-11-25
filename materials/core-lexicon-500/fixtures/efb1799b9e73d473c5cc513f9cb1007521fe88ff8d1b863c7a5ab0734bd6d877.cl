: named(sym).
: is_ben(sym).
& a named(ben).
is_ben(ok) <- named($x) & sym_eq($x,ben).
? is_ben(ok).
