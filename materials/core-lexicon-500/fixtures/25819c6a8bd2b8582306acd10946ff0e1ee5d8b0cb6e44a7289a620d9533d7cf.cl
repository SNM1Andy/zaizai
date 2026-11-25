: healthy(sym).
: down(sym).
& a !healthy(svc1).
!down($x) <- !healthy($x).
? down(svc1).
? down(svc2).
