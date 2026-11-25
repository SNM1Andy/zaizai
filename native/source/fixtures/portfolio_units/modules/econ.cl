module econ.
input cost.
input output.
input budget.
input verified.
export feasible.
export dominates.
# Cost: same currency and smallest unit. Output: same output unit and scenario.
: cost(sym,qty(cny_cent)).
: output(sym,qty(items)).
: budget(qty(cny_cent)).
: verified(sym).
: feasible(sym).
: dominates(sym,sym).

feasible($p) <- cost($p,$c) & budget($b) & output($p,$q) & verified($p) & qty_le(0@cny_cent,$c) & qty_le(0@items,$q) & qty_le($c,$b).
!feasible($p) <- cost($p,$c) & budget($b) & qty_lt($b,$c).
!feasible($p) <- cost($p,$c) & qty_lt($c,0@cny_cent).
!feasible($p) <- output($p,$q) & qty_lt($q,0@items).
!feasible($p) <- !verified($p).
# Competing observations of cost/output/budget block ranking until resolved.
!feasible($p) <- cost($p,$c) & cost($p,$d) & qty_lt($c,$d).
!feasible($p) <- output($p,$c) & output($p,$d) & qty_lt($c,$d).
!feasible($p) <- cost($p,$c) & budget($b) & budget($d) & qty_lt($b,$d).
!feasible($p) <- cost($p,$c) & !cost($p,$c).
!feasible($p) <- output($p,$q) & !output($p,$q).
!feasible($p) <- cost($p,$c) & budget($b) & !budget($b).
# A dominates B if no more costly and no less productive, with at least one strict improvement.
dominates($a,$b) <- cost($a,$ca) & cost($b,$cb) & output($a,$qa) & output($b,$qb) & qty_lt($ca,$cb) & qty_le($qb,$qa).
dominates($a,$b) <- cost($a,$ca) & cost($b,$cb) & output($a,$qa) & output($b,$qb) & qty_le($ca,$cb) & qty_lt($qb,$qa).

