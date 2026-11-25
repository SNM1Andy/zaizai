: submitted(sym).
: checked(sym).
: approved(sym).
& a submitted(case1).
checked($x) <- submitted($x).
approved($x) <- checked($x).
? approved(case1).
? approved(case2).
