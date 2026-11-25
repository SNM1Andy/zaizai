# Additional, independently scored scope for comparison with an active rollback.
: delayed(sym).
: indexed(sym).
: notify(sym).
: signed_off(sym).
@ delayed indexed notify.
notify($x) <- indexed($x) & signed_off($x).
| wish positive notify(green).
| wish positive notify(gold).
| hard negative notify(held).
& hold !notify(held).
