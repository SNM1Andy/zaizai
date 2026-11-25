: secret(sym,qty(day)).
: stale(sym).
& a secret(key1,3@day).
& b secret(key2,5@day).
stale($x) <- secret($x,$c) & qty_lt($c,4@day).
? stale(key1).
? stale(key2).
