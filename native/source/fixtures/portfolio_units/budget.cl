module budget_app.
use econ.
feasible($x) <- econ::feasible($x).
!feasible($x) <- !econ::feasible($x).
dominates($x,$y) <- econ::dominates($x,$y).
!dominates($x,$y) <- !econ::dominates($x,$y).

? feasible(amber).
? feasible(blue).
? feasible(green).
? feasible(red).
? feasible(gray).
? feasible(violet).
