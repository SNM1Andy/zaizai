: signal(sym).
: confirmed(sym).
& a signal(green).
confirmed($x) <- signal($x).
? confirmed(red).
? confirmed(green).
