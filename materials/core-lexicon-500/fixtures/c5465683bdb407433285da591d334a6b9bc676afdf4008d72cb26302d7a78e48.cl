: verdict(sym).
: settled(sym).
& a verdict(known).
settled($x) <- verdict($x).
? settled(unknown).
? settled(known).
