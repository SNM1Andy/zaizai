: wait_time(sym,qty(minute)).
: tolerable(sym).
& a wait_time(queue1,30@minute).
& b wait_time(queue2,90@minute).
tolerable($x) <- wait_time($x,$c) & qty_le($c,60@minute).
? tolerable(queue1).
? tolerable(queue2).
