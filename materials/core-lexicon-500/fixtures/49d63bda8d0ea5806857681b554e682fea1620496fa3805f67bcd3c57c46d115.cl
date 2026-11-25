: booked(sym).
: held(sym).
& a !booked(booking1).
!held($x) <- !booked($x).
? held(booking1).
? held(booking2).
