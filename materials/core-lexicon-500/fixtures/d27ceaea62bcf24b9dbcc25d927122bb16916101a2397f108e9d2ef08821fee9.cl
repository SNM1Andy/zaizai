: named(sym).
: same(sym).
& a named(one).
same($x) <- sym_eq($x,one) & named($x).
? same(one).
