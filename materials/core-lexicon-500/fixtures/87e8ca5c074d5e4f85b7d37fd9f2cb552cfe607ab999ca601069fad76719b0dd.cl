: active(sym).
: decommissioned(sym).
& a !active(host1).
!decommissioned($x) <- !active($x).
? decommissioned(host1).
? decommissioned(host2).
