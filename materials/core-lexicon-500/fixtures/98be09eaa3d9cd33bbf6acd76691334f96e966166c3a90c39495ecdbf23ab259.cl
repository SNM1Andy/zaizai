: assigned(sym).
: clear(sym).
& a assigned("caseA").
& b assigned("caseB").
& c !assigned("caseB").
clear($x) <- assigned($x).
!clear($x) <- !assigned($x).
? clear("caseB").
? clear("caseA").
