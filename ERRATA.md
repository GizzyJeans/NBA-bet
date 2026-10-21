# Errata

Errors found in Claude's own earlier outputs for this project: what was wrong, its impact, and the fix.

## E-001 · 2026-10-21 · Phase 0 reply, recon bullet on record-keeping tools

- **Wrong:** attributed the per-game "prospective by board-file git commit time" check to `Codex-NPB src/codex_npb/ledger.py`.
- **Correct:** the check lives in `src/codex_npb/pipeline_cli.py` (`_board_commit_time`, `_board_row_commit_times`) and `board.py`. `ledger.py` implements only the SHA-256 hash chain.
- **Impact:** none on any number, rule, or threshold. Attribution only.
- **Fix:** RULES R-14.1 and R-14.2 cite the right files.

## E-002 · 2026-10-21 · Phase 0 reply, "missing" bullet on CLV

- **Wrong:** said Codex-MLB computes CLV only from line or price.
- **Correct:** `Codex-MLB work/prospective_validation.py` also computes `probability_clv`: the closing selection probability minus the selection's market probability at prediction time.
- **Impact:** none on the rules. It understated reusable code. The NBA CLV definitions (R-14.4, R-14.5) stand, because the brief asks for CLV along the platform's line under the US closing fair distribution, which that code does not compute.
- **Fix:** recorded here; Phase 2 reuses that module's closing fields (RULES Appendix D).
