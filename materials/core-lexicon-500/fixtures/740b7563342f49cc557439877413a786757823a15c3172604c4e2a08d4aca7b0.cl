: items(sym,i64).
: free_shipping(sym).
& a items(cart1,3).
free_shipping($x) <- items($x,$n) & int_add($n,2,$t) & int_le($t,5).
? free_shipping(cart1).
? free_shipping(cart2).
