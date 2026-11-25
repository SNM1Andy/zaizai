# CL 0.152: Unicode in the authored compiler and profile

The authored CL grammar must opt in to a distinct quoted-symbol token. Build the canonical and forward grammars from inspectable CL source, pin resulting profiles, and show exact CLIR-7 equality with the direct compiler on equivalent programs. Keep old pinned profile bytes and their acceptance semantics unchanged. No Unicode identifiers or natural-language parsing.

Exercise grammar proof byte spans (not character columns), inline punctuation and hash comments, typed lowering and exact native evaluator output. Check a wide segmented input, malformed escapes/UTF-8, wrong literal placement or type, and wrong profile digest. Hand off the IR to an independent Linux CL process with no source; test PCGM registration of the exact resulting image if supported by the existing adapter, without any authority changes. Verify archive consistency and all prior native regression suites.
