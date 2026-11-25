: heard(sym).
: answer(sym).
heard(ben).
answer($x) <- heard($x).
? answer(ben).
