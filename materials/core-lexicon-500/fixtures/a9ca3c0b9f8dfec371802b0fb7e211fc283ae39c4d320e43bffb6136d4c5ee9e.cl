: noted(sym).
: known(sym).
noted(fact1).
known($x) <- noted($x).
? known(fact1).
