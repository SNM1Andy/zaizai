: labelled_support(sym,sym,sym).
: scoped_claim(sym,sym,sym).
scoped_claim($s,$a,$o) <- labelled_support($s,$a,$o).
!scoped_claim($s,$a,$o) <- !labelled_support($s,$a,$o).
: readable(sym).
: verified(sym).
: copy_ready(sym).
: borrow(sym).
: same_copy(sym,sym).
: ready_item(sym).
: at_location(sym,sym).
: ready_item_at(sym,sym).
: readable_at(sym,sym).
ready_item_at($x,$p) <- at_location($x,$p) & ready_item($x).
!ready_item_at($x,$p) <- at_location($x,$p) & !ready_item($x).
readable_at($x,$p) <- at_location($x,$p) & readable($x).
!readable_at($x,$p) <- at_location($x,$p) & !readable($x).
: certified(sym).
