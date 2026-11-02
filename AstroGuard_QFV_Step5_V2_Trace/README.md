# Step 5, reference Python workflow transition checks for AstroGuard V2

These scripts are intentionally limited to **two locally constructed 3-transition workflow traces** using the corrected Python gate and saved 60K held-out predictions. This is a consistency check of a *new reference wrapper* with TLA+ V2 actions, not conformance evidence for a deployed workflow. `Review` and `Withhold` are derived routing decisions, not existing executed workflow actions.

Copy `run_step5_reference_traces.py` and `trace_conformance_v2.py` into the root of your `AstroGuard_18K_macOS_Fresh_Start` folder. Run:

```
.venv/bin/python run_step5_reference_traces.py
```

Input: `RESULTS_60K/formal_verification/python_gate_replay/gate_decisions.jsonl` from Step 4. Outputs are written under `RESULTS_60K/formal_verification/python_trace_v2_reference/`. No trained models, raw light curves, TLA+ specifications, or prior results are changed.

The script selects the first release and the first review decision, executes `suite.latency.gate` with actual saved probabilities/quality values, constructs a reference workflow (Init, Infer, Assess, Release/Review), and checks transitions with the V2 checker. It does *not* instrument an existing stateful Python workflow, and these traces must not be described as observed execution traces of the astronomical processing pipeline.

A follow-up task is to implement actual runtime workflow instrumentation and run the same checker on genuine application transitions. The V2 checker rejects unsafe/stale release, accepts stale review when source is verified, and permits explicit `TerminalStep` only when all objects are terminal.
