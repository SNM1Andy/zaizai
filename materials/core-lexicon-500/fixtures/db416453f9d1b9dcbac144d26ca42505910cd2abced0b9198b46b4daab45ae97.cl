: backoff(sym,qty(ms)).
: short(sym).
& a backoff(job1,30@ms).
& b backoff(job2,90@ms).
short($x) <- backoff($x,$c) & qty_le($c,60@ms).
? short(job1).
? short(job2).
