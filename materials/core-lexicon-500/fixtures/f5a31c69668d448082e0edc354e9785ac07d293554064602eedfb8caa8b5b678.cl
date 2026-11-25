: submitted(sym).
: approved(sym).
: effective(sym).
& a submitted(case1).
approved($x) <- submitted($x).
effective($x) <- approved($x).
? effective(case1).
? effective(case2).
