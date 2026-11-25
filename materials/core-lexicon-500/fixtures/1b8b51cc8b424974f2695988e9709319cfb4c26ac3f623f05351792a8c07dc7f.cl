: rule(sym).
: special(sym).
& a rule(general).
& b rule(special).
special($x) <- rule($x) & sym_ne($x,special).
? special(general).
? special(special).
