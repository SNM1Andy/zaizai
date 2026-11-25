# 0.148 independent, relocated CL/PCGM runtime kit with both C SDKs

Publish one self-contained Linux x86-64 CPU runtime archive distinct from full buildable source; no PATH changes, installer, account, service or original repo. A non-programmer can verify and launch with absolute paths and run a toy example. A native C application can compile against either SDK with package metadata from the relocated kit. The program using the file-free SDK must not see file authority or depend on the full runtime or original checkout. PCGM stays a separate binary owning its individual/history.

Acceptance:
1. Produce archive and independently pinned manifest. A clean extraction in a path with spaces verifies without checkout or either library already configured. Verify mode, length, bytes, platform, feature bit and absence of undeclared files. Corruption, missing files or symbolic links fail before calling a runtime command.
2. On the relocated kit, independently compile through pkg-config once against each ABI profile. Confirm a C program using the pure SDK can read toy input bytes and yield actual CL proofs; perform a native evidence batch and recover the same evidence using CLI on a separate snapshot. This is host integration and package QA, not Python emulating CL.
3. From the same clean extraction, create a fresh disposable individual and exercise PCGM real observations, A/B, resume and inspect after moving the entire kit with state outside; check same identity and answers. No Alice, production or accelerator claims.
4. Full regression from the packaged source, and actual archive smoke, before setting the canonical latest runnable entry. Document two package artifacts, paths and isolation, exact CPU/OS requirements.
