: pods(sym,i64).
: few(sym).
& a pods(svc1,2).
& b pods(svc2,5).
few($x) <- pods($x,$v) & int_le($v,3).
? few(svc1).
? few(svc2).
