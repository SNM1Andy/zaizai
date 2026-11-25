: tagged(sym).
: published(sym).
: announced(sym).
& a tagged(release1).
published($x) <- tagged($x).
announced($x) <- published($x).
? announced(release1).
? announced(release2).
