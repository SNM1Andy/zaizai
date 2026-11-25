: alerts(sym,i64).
: within_slo(sym).
& a alerts(svc1,2).
& b alerts(svc2,5).
within_slo($x) <- alerts($x,$v) & int_le($v,3).
? within_slo(svc1).
? within_slo(svc2).
