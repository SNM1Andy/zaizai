: label(sym).
: tagged(sym).
& a label("order 12/3").
tagged(ok) <- label($x) & sym_eq($x,"order 12/3").
? tagged(ok).
