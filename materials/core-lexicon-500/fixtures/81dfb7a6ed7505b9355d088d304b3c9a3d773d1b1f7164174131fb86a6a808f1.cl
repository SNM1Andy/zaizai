: incident_severity(sym,i64).
: high(sym).
& a incident_severity(case1,15).
& b incident_severity(case2,20).
high($x) <- incident_severity($x,$v) & int_le(12,$v) & int_lt($v,18).
? high(case1).
? high(case2).
