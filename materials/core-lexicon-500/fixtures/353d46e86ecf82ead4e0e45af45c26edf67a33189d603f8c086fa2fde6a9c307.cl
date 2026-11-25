: access(sym).
: granted(sym).
& a access(admin).
& b access(guest).
granted($x) <- access($x) & sym_eq($x,admin).
? granted(admin).
? granted(guest).
