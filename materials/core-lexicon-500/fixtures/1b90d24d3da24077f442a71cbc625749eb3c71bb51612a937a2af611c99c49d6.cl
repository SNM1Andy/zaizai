: budget_code(sym).
: current(sym).
& a budget_code(core).
& b budget_code(legacy).
current($x) <- budget_code($x) & sym_eq($x,core).
? current(core).
? current(legacy).
