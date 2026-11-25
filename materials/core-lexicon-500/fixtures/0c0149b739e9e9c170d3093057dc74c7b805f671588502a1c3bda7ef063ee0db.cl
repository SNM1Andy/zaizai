: requested(sym).
: collected(sym).
: signed(sym).
& a requested(audit1).
collected($x) <- requested($x).
signed($x) <- collected($x).
? signed(audit1).
? signed(audit2).
