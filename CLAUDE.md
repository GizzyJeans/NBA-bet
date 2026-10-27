# Bethero NBA: instructions for Claude

Eric runs this project. Talk to him in Traditional Chinese (繁體中文). Code, comments, `rules/` and commit messages are English; reports to Eric are Traditional Chinese. Eric works on Windows: use `pathlib`, `python -m bethero_nba.<command>` entry points, and no bash-only scripts.

## Read before acting

- [`rules/nba/RULES.md`](rules/nba/RULES.md) is the rulebook and overrides the code. If the two disagree, fix the code.
- [`rules/nba/config.yaml`](rules/nba/config.yaml) holds every threshold. Each has a status and a source.
- [`rules/nba/VALIDATION.md`](rules/nba/VALIDATION.md) holds the evidence behind each `VALIDATED` value, and the shadow-mode and go-live terms.
- [`ERRATA.md`](ERRATA.md) lists errors in Claude's own earlier outputs. Check it before repeating a claim.
- Skills: `.claude/skills/nba-daily-pass` covers a slate from Eric's screenshot to settlement. `.claude/skills/nba-rule-change` covers changing a rule, a threshold or a validation.

## Invariants (never break these)

1. **Anchor first (P1).** A fair probability comes only from the US no-vig consensus. The independent model may only veto or downgrade (R-8.1). It never creates a bet, never raises a stake, and is never averaged with the market. `model.status` is OFF by Eric's decision; only he turns it on.
2. **Confidence is a label (§13).** Stakes come only from Kelly and the caps (R-12.7, §12). No flag, label or model agreement changes a stake.
3. **Provenance (P2).** Every number in a rule, the config, a report or a commit message carries `{source, N, date range, method}` or the status `UNVALIDATED`. An `UNVALIDATED` value may only make a gate stricter; it is never the reason a bet exists.
4. **Never fabricate.** If a source fails, say so and stop at the matching code (`NB-DATA`, `NB-STATUS`, `NB-STALE`). Missing data is never "no news" (R-9.2). Never fill a gap with an estimate that is not labelled as one.
5. **Stricter when unsure.** Between two readings of a rule, use the stricter one and flag it to Eric. Ask Eric only what only he can answer: the platform, his bankroll, his money. Decide the rest, state the decision and move on.
6. **Every no-bet has a code (P4).** Codes come from RULES §15, which must equal `edge.CODES` (a test checks this). A new code needs a rule, the table row and a test.
7. **Shadow mode** until Eric's explicit go-live message (R-12.7). `cfg:golive` readiness (strict, Eric 2026-10-23) is reported by `settle`. It never changes the mode by itself, and neither does Claude.
8. **Data access.**
   - Platform data comes only from Eric's screenshots. Never automate the platform.
   - Nothing fetches from NBA hosts automatically, and WAFs are never worked around. The injury report is the PDF Eric saves (R-9.1). Listed players' minutes come from ESPN box scores via sportsdataverse or from Eric's game-log screenshots, never from Sports Reference (R-9.3).
   - Network calls need `--live` (R-4.7) and go through the per-host rate limit, with the User-Agent naming the repository and never Eric's email.
   - `ODDS_API_KEY` is read from the environment only. Never print it or commit it.
   - The budget guard (`us_odds.*`) is never bypassed.
9. **Never commit:**
   - raw Odds API responses (`data/raw/`; their terms forbid redistribution);
   - per-game history (`data/history/`; the source has no licence);
   - NBA PDFs.

   Aggregates (`data/dist/`), boards, ledgers and reports are committed.
10. **Boards are committed before the first tip they cover (R-14.2).** The commit time is the evidence of pricing time.
11. **Pre-declared criteria stay fixed.** Never edit VALIDATION.md §0 after data has been seen. Results below its marker are regenerated only by `python -m bethero_nba.validate`.
12. **Prohibited in v1** (RULES §1):
    - textbook NBA constants;
    - MLB/NPB biases without NBA evidence;
    - ATS or over/under trends, and narratives, as signals;
    - parlays, props, live bets, futures;
    - stakes on any market whose format, settlement or bankroll is not `CONFIRMED`.
13. **Errors in your own earlier output.**
    - Say so explicitly and quantify the impact.
    - Fix it, and add an `ERRATA.md` entry (what was wrong, its impact, the fix).
14. **Changing a rule or threshold** follows RULES §17 (skill `nba-rule-change`):
    - bump `meta.version` and add a CHANGELOG entry;
    - a `CONFIRM` value changes only on Eric's message, with its date;
    - an `UNVALIDATED` value changes only with evidence linked to VALIDATION.md.

## Checks before every commit

```powershell
py -m pytest                      # includes config contract, cfg references and no-bet code table
py -m pyflakes src tests          # if installed
```

Commit messages say what changed and why, and name any ERRATA or CHANGELOG entry.
