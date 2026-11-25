: ordered(sym).
: shipped(sym).
: received(sym).
& a ordered(parcel1).
shipped($x) <- ordered($x).
received($x) <- shipped($x).
? received(parcel1).
? received(parcel2).
