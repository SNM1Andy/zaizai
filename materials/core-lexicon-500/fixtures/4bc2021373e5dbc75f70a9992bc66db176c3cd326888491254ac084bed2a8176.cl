: built(sym).
: tested(sym).
: released(sym).
& a built(build1).
tested($x) <- built($x).
released($x) <- tested($x).
? released(build1).
? released(build2).
