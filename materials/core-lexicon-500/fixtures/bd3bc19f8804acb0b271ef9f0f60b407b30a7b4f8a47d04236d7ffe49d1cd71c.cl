: counter_claimed(sym).
: accepted(sym).
& a counter_claimed(caseA).
& b counter_claimed(caseB).
& c !counter_claimed(caseB).
accepted($x) <- counter_claimed($x).
!accepted($x) <- !counter_claimed($x).
? accepted(caseB).
? accepted(caseA).
