: audit_item(sym).
: closed(sym).
& a audit_item(known).
closed($x) <- audit_item($x).
? closed(unknown).
? closed(known).
