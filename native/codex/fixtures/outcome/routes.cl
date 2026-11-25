: filed(sym).
: dock_context(sym).
: dock_route(sym).
: fund_route(sym).
dock_route($x) <- filed($x) & dock_context($x).
!dock_route($x) <- !dock_context($x).
fund_route($x) <- filed($x) & !dock_context($x).
!fund_route($x) <- dock_context($x).
