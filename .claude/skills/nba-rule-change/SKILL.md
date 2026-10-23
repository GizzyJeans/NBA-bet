---
name: nba-rule-change
description: Change an NBA rule, a config threshold, a status label, or a validation result. Use whenever rules/nba/RULES.md, rules/nba/config.yaml, rules/nba/VALIDATION.md or data/dist/ would change, including recording a decision from Eric or logging an error in ERRATA.md.
---

# Changing NBA rules, thresholds and validations

The change control is RULES §17. Each step below is required.

## 1. Classify the change

- **Eric's decision**, for a `CONFIRM`, `CONFIRMED` or new platform fact.
  - Quote his words and give the date in `source`; the status becomes `CONFIRMED`.
  - Never infer a decision he did not state. If his answer is ambiguous, ask instead of guessing.
- **Evidence**, for an `UNVALIDATED` value becoming `VALIDATED` or moving.
  - It needs source, N, date range, method and CI, linked to a VALIDATION.md section (R-17.3).
  - Recent profit or loss alone is never evidence.
  - A threshold under a pre-declared test stays fixed until the declared sample size is reached.
- **Design choice** (`RULE`). State the reason. If two readings are possible, take the stricter one and flag it to Eric.
- **A placeholder** may only make a gate stricter. It may never be the reason a bet exists.

## 2. Validations

- **New tests are declared before the data.** Write the criteria into VALIDATION.md and commit them before loading or computing anything. An addendum is allowed only before any statistic has been computed, and says what had been seen.
- **Never edit §0** after data has been seen.
- **Regenerate, don't hand-write.** Results come from `python -m bethero_nba.validate --history data/history/games.csv --out rules/nba/VALIDATION.md --write-dist data/dist`, which replaces only the part below the marker.
- **Then apply the values the R7 table gives,** each with its R-section in `source`.
- **Data stays local.** Per-game history and raw data stay out of git (D5); only aggregates are committed.

## 3. Edit together

1. `config.yaml`: the value, `status`, `source` (and `rationale` if `UNVALIDATED`); bump `meta.version` and `meta.updated`.
2. `RULES.md`: the rule text and the version line, if behaviour or meaning changed. Keep §15 equal to `edge.CODES`.
3. `CHANGELOG.md`: a new top entry with what changed, the evidence or Eric's words, and the consequence for bets.
4. Code and tests that read the key.
5. `README.md` if a command or input changed.

## 4. Errors in Claude's own earlier outputs

Say so to Eric explicitly, quantify the impact (numbers, gates, stakes affected, or "none"), fix it, and add `ERRATA.md` E-<next>: what was wrong, the correct version, the impact and the fix (with commit).

## 5. Check and commit

- **Run the checks.** `py -m pytest` runs the config contract, the `cfg:` references, the code table, and the rule IDs cited in `CLAUDE.md` and the skills. Fix any failure before committing.
- **Write the commit message** naming the CHANGELOG version and any ERRATA entry, then push.
