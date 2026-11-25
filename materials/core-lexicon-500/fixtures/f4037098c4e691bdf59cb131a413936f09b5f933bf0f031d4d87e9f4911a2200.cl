: timeout(sym,qty(ms)).
: short(sym).
& a timeout(api1,30@ms).
& b timeout(api2,90@ms).
short($x) <- timeout($x,$c) & qty_lt($c,60@ms).
? short(api1).
? short(api2).
