: reported(sym).
: established(sym).
& a reported(reportA).
& b reported(reportB).
& c !reported(reportB).
established($x) <- reported($x).
!established($x) <- !reported($x).
? established(reportB).
? established(reportA).
