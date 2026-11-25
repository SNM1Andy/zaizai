: permission(sym).
: restricted(sym).
& a permission(read).
& b permission(admin).
restricted($x) <- permission($x) & sym_ne($x,admin).
? restricted(read).
? restricted(admin).
