: reading(sym,i64).
: high(sym).
& a reading(sensor1,77).
high($x) <- reading($x,$v) & int_lt(50,$v).
? high(sensor1).
? high(sensor2).
