: closed(sym).
: indexed(sym).
: archived(sym).
& a closed(case1).
indexed($x) <- closed($x).
archived($x) <- indexed($x).
? archived(case1).
? archived(case2).
