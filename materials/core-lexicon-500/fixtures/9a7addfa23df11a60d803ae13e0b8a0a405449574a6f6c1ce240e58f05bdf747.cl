: paid(sym).
: shipped(sym).
: delivered(sym).
& a paid(order1).
shipped($x) <- paid($x).
delivered($x) <- shipped($x).
? delivered(order1).
? delivered(order2).
