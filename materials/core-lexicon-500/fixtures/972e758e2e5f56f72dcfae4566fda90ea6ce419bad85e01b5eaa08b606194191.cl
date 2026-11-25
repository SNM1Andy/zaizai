: deployed(sym).
: failed(sym).
: rolled_back(sym).
& a deployed(case1).
failed($x) <- deployed($x).
rolled_back($x) <- failed($x).
? rolled_back(case1).
? rolled_back(case2).
