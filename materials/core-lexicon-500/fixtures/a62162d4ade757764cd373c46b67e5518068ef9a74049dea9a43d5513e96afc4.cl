: processing(sym,qty(minute)).
: fast(sym).
& a processing(req1,30@minute).
& b processing(req2,90@minute).
fast($x) <- processing($x,$c) & qty_le($c,60@minute).
? fast(req1).
? fast(req2).
