: supported(sym).
: refuted(sym).
& a !supported(claim1).
!refuted($x) <- !supported($x).
? refuted(claim1).
? refuted(claim2).
