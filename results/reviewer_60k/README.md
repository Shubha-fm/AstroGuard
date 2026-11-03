# AstroGuard 60K experimental analysis evidence

This folder contains selected results and visualizations for the 60K astronomical classification and workflow verification study.

## Evidence groups

- `tables/`: held-out class/subclass counts, nine-model ensemble evaluation and confusion counts, matched-ensemble object bootstrap and McNemar, descriptive quality-weight sweeps, four-condition gate summaries, and validation-selected gate thresholds/outcomes.
- `figures/`: plots derived from recorded 60K experimental summaries.
- `astroguard_reviewer_from_ensembles.py`: reproducible reviewer analysis of held-out ensemble predictions. Requires the input prediction CSVs on your machine; they are not embedded in this GitHub update.
- `GATE_60K_AUDIT.md`: limitations of release-gate aggregate summaries.

## Important interpretation

- The six full-data classical models trained on 39,000 objects; the separate Quantum24 versus Classical24a and Classical24b matched study used 3,000 training objects per model. Do not mix their scores as matched comparisons.
- The ensemble-level paired bootstrap/McNemar comparisons share the same 12,001 object IDs. `seed=-1` indicates a five-seed probability ensemble, not an independent training seed.
- The four-condition ensemble summaries and validation-selected gate summaries are distinct evaluation procedures. The supplied aggregate outputs do not fully specify a standalone uncertainty threshold or separate Review vs Withhold routing counts.
- No model result proves independently labeled astronomical truth or a deployed system safety guarantee.
- The extended TLC log independently records 120,858,085 generated states and 14,144,709 distinct states. Its bounded safety interpretation must match the exact configuration.

Full research record DOI supplied by depositor: https://doi.org/10.5281/zenodo.23892124

This upload intentionally excludes the manuscript and large checkpoints/raw datasets.
