: reproduced(sym,sym).
: verified(sym).
& a reproduced("labA",result1).
& b reproduced("labB",result1).
verified($x) <- reproduced($x,result1).
? verified("labA").
? verified("labB").
