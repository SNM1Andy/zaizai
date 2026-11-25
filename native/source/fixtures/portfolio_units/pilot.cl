module pilot_app.
use econ.
feasible($x) <- econ::feasible($x).
!feasible($x) <- !econ::feasible($x).
dominates($x,$y) <- econ::dominates($x,$y).
!dominates($x,$y) <- !econ::dominates($x,$y).

? feasible(test_a).
? feasible(test_b).
