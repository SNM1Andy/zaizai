: stance(sym).
: decided(sym).
& a stance(known).
decided($x) <- stance($x).
? decided(unknown).
? decided(known).
