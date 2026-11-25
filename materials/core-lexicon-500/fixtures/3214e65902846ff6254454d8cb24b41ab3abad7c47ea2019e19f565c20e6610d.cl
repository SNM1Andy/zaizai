: start(i64).
: computed(i64).
& seed start(9223372036854775807).
computed($y) <- start($x) & int_add($x,1,$y).
? computed(0).
