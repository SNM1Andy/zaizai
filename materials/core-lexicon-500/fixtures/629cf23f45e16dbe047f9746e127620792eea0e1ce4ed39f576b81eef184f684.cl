: paid(sym).
: shipped(sym).
& a paid(order1).
shipped($x) <- paid($x).
? shipped(order1).
