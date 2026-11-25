: antecedent(sym).
: implied(sym).
: consequent(sym).
& a antecedent(case1).
implied($x) <- antecedent($x).
consequent($x) <- implied($x).
? consequent(case1).
? consequent(case2).
