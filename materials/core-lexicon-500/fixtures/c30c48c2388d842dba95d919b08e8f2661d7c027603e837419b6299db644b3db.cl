: scheduled(sym).
: copied(sym).
: verified(sym).
& a scheduled(backup1).
copied($x) <- scheduled($x).
verified($x) <- copied($x).
? verified(backup1).
? verified(backup2).
