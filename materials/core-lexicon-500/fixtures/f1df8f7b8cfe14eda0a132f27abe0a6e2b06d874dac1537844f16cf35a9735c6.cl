: drafted(sym).
: done(sym).
: verified(sym).
& a drafted(mile1).
done($x) <- drafted($x).
verified($x) <- done($x).
? verified(mile1).
? verified(mile2).
