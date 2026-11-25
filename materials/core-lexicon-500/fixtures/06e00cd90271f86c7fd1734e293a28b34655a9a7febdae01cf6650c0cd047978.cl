: signal(sym,i64).
: in_band(sym).
& a signal(sig1,15).
& b signal(sig2,20).
in_band($x) <- signal($x,$v) & int_le(12,$v) & int_lt($v,18).
? in_band(sig1).
? in_band(sig2).
