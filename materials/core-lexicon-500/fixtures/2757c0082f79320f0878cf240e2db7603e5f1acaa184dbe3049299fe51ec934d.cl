: dependency_version(sym).
: pinned(sym).
& a dependency_version(caseA).
& b dependency_version(caseB).
pinned($x) <- dependency_version($x) & sym_eq($x,caseA).
? pinned(caseA).
? pinned(caseB).
