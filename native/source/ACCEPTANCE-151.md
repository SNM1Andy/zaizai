# CL / PCGM 0.151: exact Unicode symbolic observations and logic

Extend native grammar with bounded quoted UTF-8 constants of the existing `sym` type. This is not a natural-language parser, tokenizer, translation model, or Unicode predicate/module identifier support. Quoted constants have exact scalar bytes and a distinct, whitespace-free canonical wire syntax to survive package locks, journals and process handoff. Legacy bare and numeric atoms keep their syntax and proof bytes. No normalization/locale shortcuts. Reject malformed UTF-8, embedded controls and invalid escapes; distinguish visible input explicitly.

Acceptance:
- Real native CL language input contains Chinese, several scripts, embedded punctuation and a literal that looks like program syntax. Link a workspace and independently reopen exact package/IR. Confirm correct join and exact typed proof, literal not code, conflict/unknown behaves unchanged, wrong type/UTF-8 rejected. CLIR format advertises new capability only for programs actually containing quoted constants, and canonical wire roundtrips without changing earlier CLIR versions.
- Separate C memory SDK and native CLI produce identical proof bytes for a relocated detached workspace with no source files.
- Actual PCGM observation, query, withdrawal, hard stop and A/B recovery use exact stamped identity, decoded human-readable reason and durable escaped value; quoted symbols do not change PCGM evaluation authority. Scope limits and stable ASCII identifiers remain. No Windows/CUDA claim.
