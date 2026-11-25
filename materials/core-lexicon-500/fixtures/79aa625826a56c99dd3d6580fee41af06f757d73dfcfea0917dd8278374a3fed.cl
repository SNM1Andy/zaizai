: saw(sym,sym).
: seen(sym).
& a saw(alice,car).
& b saw(bob,car).
seen($x) <- saw($x,car).
? seen(alice).
? seen(bob).
