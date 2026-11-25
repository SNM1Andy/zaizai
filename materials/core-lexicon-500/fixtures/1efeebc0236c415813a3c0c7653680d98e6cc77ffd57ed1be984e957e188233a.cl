: detected(sym).
: triggered(sym).
: handled(sym).
& a detected(case1).
triggered($x) <- detected($x).
handled($x) <- triggered($x).
? handled(case1).
? handled(case2).
