: verified_at(sym,sym).
verified_at($x,$p) <- at_location($x,$p) & verified($x).
!verified_at($x,$p) <- at_location($x,$p) & !verified($x).
: copy_ready_at(sym,sym).
copy_ready_at($x,$p) <- at_location($x,$p) & copy_ready($x).
!copy_ready_at($x,$p) <- at_location($x,$p) & !copy_ready($x).
: borrow_at(sym,sym).
borrow_at($x,$p) <- at_location($x,$p) & borrow($x).
!borrow_at($x,$p) <- at_location($x,$p) & !borrow($x).
