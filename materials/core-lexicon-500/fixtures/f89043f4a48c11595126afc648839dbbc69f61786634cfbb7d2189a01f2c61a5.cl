: paid(sym).
: refunded(sym).
& a !paid(order9).
!refunded($x) <- !paid($x).
? refunded(order9).
? refunded(order8).
