: heard(sym).
: trusted(sym).
: answer(sym).
& a heard(ben).
& b trusted(ben).
& c heard(cai).
answer($x) <- heard($x) & trusted($x).
? answer(ben).
? answer(cai).
