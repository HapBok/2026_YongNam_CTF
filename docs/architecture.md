# Architecture

User → import/prescan → SQLite queue → dynamic Workers w01..w08 → explicit Codex exec → JSON handoff → Supervisor validation/promotion → next Stage. All routing is central. Profile names are allowlisted; model recommendations are advisory.

Intake/Triage/Rescue/Verify use fresh sessions. Only the same Solve profile may resume an explicit session ID. Worker ID does not imply category, profile or session. Verify never inherits the solve conversation. Stage Task records generation, lease ID, worker ID, hypothesis key and parent.

SQLite WAL and BEGIN IMMEDIATE serialize claims and publication. Active includes LEASED/STARTING/RUNNING/CANCELLING/COMMITTING. Global cap 8; breadth one run/problem; depth two distinct hypothesis keys/problem. Queue order is priority DESC, creation time, task ID. Verify priority 100; initial classification 90; quick 80; solve 50..70; rescue 40..45.

Supervisor singleton uses Linux flock. Worker IDs have heartbeat tokens. Stale generation and expired lease cannot publish. Cancellation reserves the slot until process exit is confirmed. Orphans freeze rather than replay unknown remote side effects. Promoted artifact namespaces include Task ID, so attempts cannot silently overwrite one another. Publication occurs under the same SQLite write transaction as generation checks; crash between file copy and DB commit is reconciled by immutable hash checks on retry.

Scope is immutable for the run, represented by SHA-256. Scope changes require a new approved run workspace. The scope manifest is a policy contract; host allowlisting is not a full network firewall. The Codex workspace-write sandbox remains active. Do not treat WSL alone as containment against hostile kernel exploits; use a stronger isolated VM for such artifacts.

Windows Terminal launches background Supervisor and 8 visible worker tabs. The Linux launcher instead starts Supervisor plus 8 child worker processes in one terminal. Both share the same global queue cap.

The optional make-toml controller transcribes statement screenshots before import, using native CLI image attachments and a separate metadata output schema. It deterministically writes challenge.toml in the operator-specified problem folder, never scope.toml, and never overwrites an existing TOML. Uncertain extraction produces only a review draft. It reserves one slot in the same SQLite ledger: a waiting/running metadata reservation reduces worker claim capacity by one, and a running reservation counts toward peak_active. A stale reservation does not expire open; recover requires proof that the owner and child process group have stopped. Metadata generation is sequential and is not a folder watcher or automatic problem submission.

