# whole-line comment
# & a note(ghost).
: note(sym).
: seen(sym).
& a note("a#b").
seen(marked) <- note($x) & sym_eq($x,"a#b").
? seen(marked).
? seen(ghost).
