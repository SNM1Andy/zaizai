: tenant(sym).
: primary(sym).
& a tenant(tenantA).
& b tenant(tenantB).
primary($x) <- tenant($x) & sym_eq($x,tenantA).
? primary(tenantA).
? primary(tenantB).
