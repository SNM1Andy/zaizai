: opened(sym).
: assigned(sym).
: done(sym).
& a opened(case1).
assigned($x) <- opened($x).
done($x) <- assigned($x).
? done(case1).
? done(case2).
