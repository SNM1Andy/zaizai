: env(sym).
: allowed(sym).
& a env(prod).
& b env(staging).
allowed($x) <- env($x) & sym_eq($x,prod).
? allowed(prod).
? allowed(staging).
