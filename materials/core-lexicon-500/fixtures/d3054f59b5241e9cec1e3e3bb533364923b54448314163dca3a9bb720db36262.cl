: asked(sym).
: answered(sym).
: closed(sym).
& a asked(gap1).
answered($x) <- asked($x).
closed($x) <- answered($x).
? closed(gap1).
? closed(gap2).
