: age_days(sym,i64).
: new(sym).
& a age_days(record1,2).
& b age_days(record2,5).
new($x) <- age_days($x,$v) & int_le($v,3).
? new(record1).
? new(record2).
