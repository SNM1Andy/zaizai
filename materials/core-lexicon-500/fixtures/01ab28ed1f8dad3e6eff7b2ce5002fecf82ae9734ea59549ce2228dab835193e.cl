: submitted(sym).
: checked(sym).
: verified(sym).
& a submitted(case1).
checked($x) <- submitted($x).
verified($x) <- checked($x).
? verified(case1).
? verified(case2).
