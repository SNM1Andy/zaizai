: evidence_item(sym).
: filled(sym).
& a evidence_item(known).
filled($x) <- evidence_item($x).
? filled(unknown).
? filled(known).
