: geom_afford(sym).
: geom_ready(sym).
: geom_visible(sym).
: geom_blocked(sym).
: geom_permitted(sym).
: geom_priority(sym).
geom_permitted(inspect) <- geom_visible(signal) & geom_afford(inspect).
geom_permitted(work) <- geom_ready(task) & geom_afford(work).
!geom_permitted(work) <- geom_blocked(work).
geom_permitted(wait) <- geom_visible(signal).
geom_permitted(wait) <- geom_ready(task).
geom_permitted(wait) <- geom_blocked(work).
geom_priority(inspect) <- geom_visible(signal).
geom_priority(work) <- geom_ready(task).
