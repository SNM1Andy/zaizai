: decision(sym).
: effective(sym).
& a decision("caseA").
& b decision("caseB").
& c !decision("caseB").
effective($x) <- decision($x).
!effective($x) <- !decision($x).
? effective("caseB").
? effective("caseA").
