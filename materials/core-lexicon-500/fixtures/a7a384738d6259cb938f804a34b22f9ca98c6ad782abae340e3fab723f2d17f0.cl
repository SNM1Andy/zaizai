: chain_step(sym).
: complete(sym).
& a chain_step(known).
complete($x) <- chain_step($x).
? complete(unknown).
? complete(known).
