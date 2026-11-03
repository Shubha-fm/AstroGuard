# 60K gate-evidence audit

Data source: user-uploaded AstroGuard_60K_Final_Gate_Evidence.zip, 13 original CSVs.

- `ensemble_4way_release_gate.csv` in each training-budget folder reports actual held-out (12,001) released counts, coverage, released accuracy/error. It has **no** columns for thresholds, reason codes, review vs withhold or per-object gate outcomes.
- `validation_selected_gate.csv` reports five per-seed rows per model with selected confidence and quality thresholds and validation/test coverage and risk; full RF confidence is 0.8, others 0.9, quality 0.2. This is a separate seed-level selection analysis, not the same four-condition ensemble-policy test.
- The nine validation ensemble CSVs contain 8,999 rows each and 30 columns. They support reproduction of descriptive metrics, but no record of the exact uncertainty cutoff or operational source predicate.
- Counts and rates in manuscript tables are copied from original aggregate CSVs (rounding only). Mean seed-level figures are computed over the five rows of each model.
- Never report non-released objects as all withheld or all reviewed; the archive does not distinguish these.
- Do not claim the unreported tau_U has been validated.
