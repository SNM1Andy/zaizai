: reviewed(sym).
: signed(sym).
: released(sym).
& a reviewed(case1).
signed($x) <- reviewed($x).
released($x) <- signed($x).
? released(case1).
? released(case2).
