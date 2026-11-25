: tag(sym).
: matched(sym).
& a tag(tagA).
& b tag(tagB).
matched($x) <- tag($x) & sym_eq($x,tagA).
? matched(tagA).
? matched(tagB).
