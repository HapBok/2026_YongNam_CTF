# Implementation and readiness audit

Implementation and live readiness are separate gates. Inspect reports/acceptance.json, reports/rehearsal/ and reports/preflight.json for authoritative results. The source specification is docs/design-source.md.

P0: folder/rules/contracts, SQLite/queue/lease, 8-worker Supervisor, Codex adapter, import/prescan, profiles/prompts, cancel/generation fence, artifact checks/promotion, launchers/status, unit/fault/integration tests and rehearsal scripts.

P1 included: read-only status watch, manual quota input, per-profile reported token totals, Snapshot, export and verified write-up drafts. P2 native subagents/distributed orchestration remains deliberately disabled for contest v1.

Live constraints must not be inferred from offline tests: login, account model availability, Daybreak approval, quota headroom, official event scope and the real problem-solving rate. Go requires live preflight plus clean local acceptance evidence. Personal 13+/team 25 are performance goals, not claimed verified outcomes.

Implementation adaptations found in real tests: project-local Linux Codex 0.162.1 replaces the unusable WSL Windows npm shim; existing same-user Windows login is linked locally without printing tokens; NTFS flag files use user/SYSTEM/Administrators ACLs instead of claiming chmod enforcement. The real-model owned crypto fixture and explicit Daybreak solve/verify fixture passed. These fixtures do not measure real contest difficulty.

The production scope remains an operator-supplied configuration. models_ready means model/effort/Daybreak canaries passed; ready also requires an initialized authorized scope. A missing scope correctly keeps automatic contest dispatch disabled.

