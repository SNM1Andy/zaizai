# Synthetic instrument, parcel and calibration cases. No declared goals.
: reading(sym,i64).
: checked(i64).
: ready(i64).
: arrival(sym).
: inspected(sym).
: released(sym).
: calibration(sym).
: allowed(sym).
: measured(sym).
: calibrated(sym).
ready($n) <- reading(sensor,$n) & checked($n).
!ready($n) <- !checked($n).
released($x) <- arrival($x) & inspected($x).
!released($x) <- !inspected($x).
calibrated($x) <- calibration($x) & allowed($x) & measured($x).
!calibrated($x) <- calibration($x) & allowed($x) & !measured($x).
