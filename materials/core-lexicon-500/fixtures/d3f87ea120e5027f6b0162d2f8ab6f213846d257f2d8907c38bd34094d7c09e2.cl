: caused(sym).
: led(sym).
: resulted(sym).
& a caused(case1).
led($x) <- caused($x).
resulted($x) <- led($x).
? resulted(case1).
? resulted(case2).
