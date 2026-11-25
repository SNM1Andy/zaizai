: filed(sym).
: reviewed(sym).
: decided(sym).
& a filed(case1).
reviewed($x) <- filed($x).
decided($x) <- reviewed($x).
? decided(case1).
? decided(case2).
