: planned(sym).
: booked(sym).
: confirmed(sym).
& a planned(booking1).
booked($x) <- planned($x).
confirmed($x) <- booked($x).
? confirmed(booking1).
? confirmed(booking2).
