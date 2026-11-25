# Synthetic predeclared sorting-line policy. The two observed stalls and the
# held-out parcel share the same sensor signature. Crushed parcels are vetoed.
: stalled(sym).
: scanned(sym).
: release(sym).
: packed(sym).
: note(sym).
@ stalled scanned release.
release($x) <- scanned($x) & packed($x).
| wish positive release(amber).
| wish positive release(blue).
| wish positive release(copper).
| hard negative release(crushed).
& veto !release(crushed).
