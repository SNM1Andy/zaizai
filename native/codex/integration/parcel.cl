# Synthetic sorting desk. Host-authored authority and fixed signed criteria.
: stalled(sym).
: scanned(sym).
: certified(sym).
: eligible(sym).
: release(sym).
@ stalled eligible release.
eligible($x) <- scanned($x) & certified($x).
!eligible($x) <- !certified($x).
| wish positive release(amber).
| wish positive release(blue).
| hard negative release(crushed).
& veto !release(crushed).
& stall_a stalled(amber).
& scan_a scanned(amber).
& cert_a certified(amber).
& stall_b stalled(blue).
& scan_b scanned(blue).
