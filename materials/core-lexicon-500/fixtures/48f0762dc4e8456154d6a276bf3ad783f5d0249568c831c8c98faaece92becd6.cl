: heard(sym).
: known(sym).
heard(ben).
known($x) <- heard($x).
? known(ben).
