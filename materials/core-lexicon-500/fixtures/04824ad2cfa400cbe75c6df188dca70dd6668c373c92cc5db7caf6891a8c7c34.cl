: role(sym).
: elevated(sym).
& a role(owner).
& b role(viewer).
elevated($x) <- role($x) & sym_eq($x,owner).
? elevated(owner).
? elevated(viewer).
