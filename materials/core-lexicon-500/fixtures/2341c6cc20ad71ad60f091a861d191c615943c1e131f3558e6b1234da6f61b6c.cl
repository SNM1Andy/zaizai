: heard(sym).
: answer(sym).
& a heard(ben).
& b heard(du).
& c !heard(du).
answer($x) <- heard($x).
!answer($x) <- !heard($x).
? answer(du).
? answer(ben).
