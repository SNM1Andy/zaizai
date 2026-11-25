: paid(sym).
: shipped(sym).
& a paid(order1).
paid($x) <- shipped($x).
? shipped(order1).
