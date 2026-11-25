: ttl(sym,qty(hour)).
: short(sym).
& a ttl(token1,30@hour).
& b ttl(token2,90@hour).
short($x) <- ttl($x,$c) & qty_le($c,60@hour).
? short(token1).
? short(token2).
