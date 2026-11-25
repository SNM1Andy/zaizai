: observed(sym).
: supported(sym).
: proven(sym).
& a observed(case1).
supported($x) <- observed($x).
proven($x) <- supported($x).
? proven(case1).
? proven(case2).
