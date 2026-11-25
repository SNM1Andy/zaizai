: delay(sym,qty(minute)).
: tolerable(sym).
& a delay(run1,30@minute).
& b delay(run2,90@minute).
tolerable($x) <- delay($x,$c) & qty_le($c,60@minute).
? tolerable(run1).
? tolerable(run2).
