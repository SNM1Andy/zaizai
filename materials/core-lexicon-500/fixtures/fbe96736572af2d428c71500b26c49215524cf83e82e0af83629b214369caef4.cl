: fiscal_year(sym,i64).
: early(sym).
& a fiscal_year(year1,2024).
& b fiscal_year(year2,2026).
early($x) <- fiscal_year($x,$v) & int_le($v,2025).
? early(year1).
? early(year2).
