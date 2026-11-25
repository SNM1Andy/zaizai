# PCGM 0.146: descriptor-anchored durable sidecars

Input: synthetic PCGM identities, actual filesystem and Linux native executables. Assets include the historical snapshot and journal segments needed for rollback and retained CL artifacts needed for comparison and restart.

- Bind the state and durable asset folders to one opened state root. Folder and immutable member operations are anchored, with no following links at either leaf and no replacement of existing objects. A missing optional vault may use the prior exact, digest-checked import location; an invalid or unreadable vault/member cannot silently fall back.
- Publish object bytes durably before making them reachable from state. Refuse wrong bytes at immutable addresses; already-published identical bytes may be reused. Reopen and recover the exact identity, history, proof, recorded choices and active rules after process exit or A/B handoff.
- Use actual Linux filesystem behaviors for tests (regular directories, links, missing files, moved folders, process exit); no virtual test substituting for platform compatibility. Preserve previous state envelope, CLI responsibilities and history format. Only the Linux adapter has been run; neither Windows nor CUDA is claimed. No production identity/data.
