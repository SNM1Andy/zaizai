# This profile authorizes only the normal, statically permitted project graph.
: scope_module(sym).
: scope_direct(sym,sym).
: scope_public(sym,sym).
: scope_input(sym,sym).
: scope_call(i64,sym,sym,sym).
: scope_role(i64,sym).
: scope_local_role(sym).
: scope_import_role(sym).
: scope_allow(i64).
scope_local_role(read).
scope_local_role(write).
scope_local_role(fold).
scope_import_role(read).
scope_import_role(fold).
scope_allow($site) <- scope_call($site,$module,$module,$predicate) & scope_module($module) & scope_role($site,$role) & scope_local_role($role).
scope_allow($site) <- scope_call($site,$caller,$provider,$predicate) & scope_direct($caller,$provider) & scope_public($provider,$predicate) & scope_role($site,$role) & scope_import_role($role).
scope_allow($site) <- scope_call($site,$module,$module,$predicate) & scope_module($module) & scope_input($module,$predicate) & scope_role($site,data).
scope_allow($site) <- scope_call($site,$caller,$provider,$predicate) & scope_direct($caller,$provider) & scope_input($provider,$predicate) & scope_role($site,data).
