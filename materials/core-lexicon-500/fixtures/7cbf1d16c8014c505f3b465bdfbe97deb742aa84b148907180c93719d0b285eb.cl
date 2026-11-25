: observed(sym).
: attributed(sym).
: assigned(sym).
& a observed(case1).
attributed($x) <- observed($x).
assigned($x) <- attributed($x).
? assigned(case1).
? assigned(case2).
