: interval(sym,qty(minute)).
: too_close(sym).
& a interval(pair1,3@minute).
& b interval(pair2,5@minute).
too_close($x) <- interval($x,$c) & qty_lt($c,4@minute).
? too_close(pair1).
? too_close(pair2).
