# PCGM portable replay audit for one observation correction

Add an opt-in local audited observation batch: retain a pinned pre-commit snapshot, exact request and normal atomic state/result without changing ordinary batches or decision authority. A read-only channel can reconstruct the before and after states from historical material, verify the recorded event/notice span, and return exact typed before/after goal proofs and proof identities even after new evidence arrives. Include retained material in actual compact export, staged-copy activation and A/B ownership handoff; refuse missing/corrupt basis or wrong request pin and do not auto-repair. No deployment or change to CL inference itself.

Native tests will verify exact retry does not add receipts, a later observation changes the current proof while the audit remains byte-identical, transfer restores all pins, stale/corrupt inputs reject, and ordinary batch without an archive cannot claim reconstructed evidence.
