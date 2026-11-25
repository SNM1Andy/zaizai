: drafted(sym).
: reviewed(sym).
: published(sym).
& a drafted(post1).
reviewed($x) <- drafted($x).
published($x) <- reviewed($x).
? published(post1).
? published(post2).
