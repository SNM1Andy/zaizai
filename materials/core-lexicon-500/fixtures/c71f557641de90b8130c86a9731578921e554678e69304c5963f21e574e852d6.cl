: planned(sym).
: reached(sym).
: signed_off(sym).
& a planned(case1).
reached($x) <- planned($x).
signed_off($x) <- reached($x).
? signed_off(case1).
? signed_off(case2).
