: blocked_name(sym).
: blocked(sym).
& a blocked_name(caseA).
& b blocked_name(caseB).
blocked($x) <- blocked_name($x) & sym_ne($x,caseB).
? blocked(caseA).
? blocked(caseB).
