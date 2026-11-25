: opened(sym).
: assigned(sym).
: closed(sym).
& a opened(ticket1).
assigned($x) <- opened($x).
closed($x) <- assigned($x).
? closed(ticket1).
? closed(ticket2).
