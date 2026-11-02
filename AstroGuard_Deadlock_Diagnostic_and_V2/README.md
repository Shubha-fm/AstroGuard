# AstroGuard deadlock diagnostics and revised candidate model

**Status: candidate correction; NOT TLC-verified here.** Do not claim the revised model passes until you run the actual TLC commands and save the logs.

## Why the old model can stop

1. All objects can reach terminal stages `Released`, `Review`, `Withheld`, with `MaxVersion` exhausted. The old `Next` has no explicit terminal stuttering branch, so TLC reports ordinary completion as a deadlock.
2. After a model reload, an object in `Assessed` may have a stale `assessedVersion`. If all confidence/quality flags are true and retries are exhausted, the old release, review, and withhold guards can all be disabled. This is a genuine lack-of-progress risk.

## What changes in this candidate

- `TerminalStep` is an explicit stuttering action **only when every object is in a terminal stage**, so deadlocks in nonterminal states remain visible.
- `Review(o)` now admits `assessedVersion[o] # modelVersion` for `sourceOK[o]`, routing stale assessments to manual review. `Withhold(o)` still handles unverified sources, and `Release(o)` still demands freshness and all four quality gates.

This is a semantic change to the workflow. It must be documented in a publication and independently checked.

## Inspect actual first failure before using the patch

```bash
grep -n -A 8 -B 2 'Error:' RESULTS_60K/formal_verification/deadlock/tlc_deadlock_check.log
grep -n -A 4 -B 2 'Error:' RESULTS_60K/formal_verification/extended/objects_1_deadlock_enabled.log
grep -n -A 4 -B 2 'Error:' RESULTS_60K/formal_verification/extended/objects_2_deadlock_enabled.log
grep -n -A 4 -B 2 'Error:' RESULTS_60K/formal_verification/extended_3/objects_3_deadlock_enabled.log
```

## Run the separate revised model without replacing the original

Copy the `tla_v2/` directory into the AstroGuard project next to `verify_tlc_bounds.py`.

Run **one and two objects**:

```bash
.venv/bin/python verify_tlc_bounds.py \
  --jar ./tla2tools.jar \
  --tla ./tla_v2/AstroGuardActor.tla \
  --objects 1 2 \
  --deadlock enabled \
  --timeout 900 \
  --out RESULTS_60K/formal_verification/deadlock_v2
```

Then **three objects**:

```bash
.venv/bin/python verify_tlc_bounds.py \
  --jar ./tla2tools.jar \
  --tla ./tla_v2/AstroGuardActor.tla \
  --objects 3 \
  --deadlock enabled \
  --timeout 1800 \
  --out RESULTS_60K/formal_verification/deadlock_v2_3
```

If the revised model fails, report the exact error and counterexample, fix the underlying problem, and repeat. The 3-object configuration may be expensive in time and memory.

## Evidence to archive

- Original failing logs and cfg files
- Revised `AstroGuardActor.tla`, `CHANGES.diff`
- Versioned cfg, new TLC logs and JSON summaries
- TLC JAR SHA-256 and revised TLA+ source SHA-256
- A clear discussion that this is an abstract protocol checked for 1–3 objects, not 60,000 astronomical objects

## Preserving the existing verified baseline

Do not overwrite `tla/AstroGuardActor.tla` or the existing `RESULTS_60K/formal_verification/tlc` files. The original safety-only run remains a valid historical bounded result; the new checks use a modified specification and have their own provenance.
