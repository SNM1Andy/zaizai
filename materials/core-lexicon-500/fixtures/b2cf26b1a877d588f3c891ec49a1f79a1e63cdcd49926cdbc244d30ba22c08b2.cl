: found(sym).
: triaged(sym).
: closed(sym).
& a found(case1).
triaged($x) <- found($x).
closed($x) <- triaged($x).
? closed(case1).
? closed(case2).
