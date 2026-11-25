: named(sym).
: same(sym).
& a named(one).
same($x) <- named($x) & sym_eq($x,one).
? same(one).
? same(two).
