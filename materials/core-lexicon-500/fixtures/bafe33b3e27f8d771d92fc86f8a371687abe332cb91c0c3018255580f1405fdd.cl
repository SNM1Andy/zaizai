: instrumented(sym).
: alerted(sym).
: responded(sym).
& a instrumented(case1).
alerted($x) <- instrumented($x).
responded($x) <- alerted($x).
? responded(case1).
? responded(case2).
