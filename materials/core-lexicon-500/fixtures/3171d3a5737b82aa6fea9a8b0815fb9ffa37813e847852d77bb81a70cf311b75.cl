: recorded(sym).
: traced(sym).
: confirmed(sym).
& a recorded(case1).
traced($x) <- recorded($x).
confirmed($x) <- traced($x).
? confirmed(case1).
? confirmed(case2).
