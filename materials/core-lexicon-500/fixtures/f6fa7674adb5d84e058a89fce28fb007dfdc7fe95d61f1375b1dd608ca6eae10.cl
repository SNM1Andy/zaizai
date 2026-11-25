: latency(sym,qty(ms)).
: fast(sym).
& a latency(api1,30@ms).
& b latency(api2,90@ms).
fast($x) <- latency($x,$c) & qty_le($c,60@ms).
? fast(api1).
? fast(api2).
