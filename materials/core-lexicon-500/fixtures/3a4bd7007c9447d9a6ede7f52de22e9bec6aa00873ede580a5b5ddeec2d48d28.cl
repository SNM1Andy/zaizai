: tag(sym).
: excluded(sym).
& a tag("tagA").
& b tag("tagB").
excluded($x) <- tag($x) & sym_ne($x,"tagB").
? excluded("tagA").
? excluded("tagB").
