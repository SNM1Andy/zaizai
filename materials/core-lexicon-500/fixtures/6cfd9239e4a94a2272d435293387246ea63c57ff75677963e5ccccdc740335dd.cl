: sourced(sym).
: reliable(sym).
& a sourced(caseA).
& b sourced(caseB).
& c !sourced(caseB).
reliable($x) <- sourced($x).
!reliable($x) <- !sourced($x).
? reliable(caseB).
? reliable(caseA).
