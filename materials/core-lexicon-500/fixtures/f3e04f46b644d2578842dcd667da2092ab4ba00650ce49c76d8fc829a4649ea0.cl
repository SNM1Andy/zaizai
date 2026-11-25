: restored(sym).
: verified(sym).
: cut_over(sym).
& a restored(case1).
verified($x) <- restored($x).
cut_over($x) <- verified($x).
? cut_over(case1).
? cut_over(case2).
