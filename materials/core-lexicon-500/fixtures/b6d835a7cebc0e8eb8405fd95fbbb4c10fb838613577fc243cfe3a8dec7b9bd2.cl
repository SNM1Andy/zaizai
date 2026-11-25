: retries(sym,i64).
: reached(sym).
& a retries(job1,2).
reached($x) <- retries($x,$n) & int_add($n,2,$t) & int_le($t,4).
? reached(job1).
? reached(job2).
