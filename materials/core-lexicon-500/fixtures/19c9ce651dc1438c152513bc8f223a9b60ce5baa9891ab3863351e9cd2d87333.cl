: region(sym).
: home(sym).
& a region(east).
& b region(west).
home($x) <- region($x) & sym_eq($x,east).
? home(east).
? home(west).
