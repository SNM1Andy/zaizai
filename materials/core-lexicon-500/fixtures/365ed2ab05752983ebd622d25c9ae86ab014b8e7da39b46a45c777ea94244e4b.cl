: published(sym).
: retracted(sym).
& a !published("caseA").
!retracted($x) <- !published($x).
? retracted("caseA").
? retracted("caseB").
