: review_cycle(sym,i64).
: short(sym).
& a review_cycle(review1,2).
& b review_cycle(review2,5).
short($x) <- review_cycle($x,$v) & int_le($v,3).
? short(review1).
? short(review2).
