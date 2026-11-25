: declared(sym).
: resolved(sym).
: pinned(sym).
& a declared(dep1).
resolved($x) <- declared($x).
pinned($x) <- resolved($x).
? pinned(dep1).
? pinned(dep2).
