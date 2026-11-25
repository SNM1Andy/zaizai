: prereq(sym).
: ready(sym).
: started(sym).
& a prereq(job1).
ready($x) <- prereq($x).
started($x) <- ready($x).
? started(job1).
? started(job2).
