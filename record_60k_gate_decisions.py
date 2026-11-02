#!/usr/bin/env python3
"""Replay actual 60K held-out ensemble records through the corrected Python gate.

This is a gate-decision audit, NOT runtime workflow tracing or a TLA+ refinement proof.
It does not alter model predictions or existing analysis results.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

import pandas as pd
from suite.analyze import quality
from suite.common import config
from suite.latency import gate


def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="RESULTS_60K/classical_15ep/analysis/ensemble_rf_test_128.csv")
    parser.add_argument("--out", default="RESULTS_60K/formal_verification/python_gate_replay")
    args = parser.parse_args()
    src, out = Path(args.input), Path(args.out)
    if not src.is_file():
        parser.error(f"Missing input: {src}")
    df = pd.read_csv(src, dtype={"object_id": "string"})
    required = {"object_id", "model", "split", "prefix", "confidence",
                "epistemic_uncertainty", "n_valid", "median_mag_err",
                "n_g", "n_r", "source_verified"}
    missing = required - set(df.columns)
    if missing:
        parser.error(f"Missing input columns: {sorted(missing)}")
    if len(df) == 0 or df.object_id.isna().any() or df.object_id.duplicated().any():
        parser.error("Input must contain distinct, nonempty object IDs")
    if not df.split.eq("test").all() or not pd.to_numeric(df.prefix, errors="coerce").eq(128).all():
        parser.error("Expected only full-prefix (128) held-out test records")
    if df.model.nunique() != 1 or not str(df.model.iloc[0]).endswith("_ensemble"):
        parser.error("Expected exactly one ensemble model in the input")

    conf = pd.to_numeric(df.confidence, errors="coerce")
    unc = pd.to_numeric(df.epistemic_uncertainty, errors="coerce")
    q = quality(df, config()["quality_weights"])
    verified = df.source_verified.astype(str).str.lower().isin(("true", "1", "yes"))
    thresholds = config()["gate"]
    results = []
    count = {"Release": 0, "Review": 0, "Withhold": 0}
    for i in range(len(df)):
        c, u, qual = float(conf.iloc[i]), float(unc.iloc[i]), float(q[i])
        if not all(map(math.isfinite, (c, u, qual))):
            parser.error(f"Non-finite decision input at row {i}")
        s = bool(verified.iloc[i])
        approved = gate(c, qual, s, epistemic_uncertainty=u)
        if not isinstance(approved, bool):
            approved = bool(approved)
        independent_oracle = (s and c >= thresholds["confidence"]
                              and qual >= thresholds["quality"]
                              and u <= thresholds["epistemic_uncertainty"])
        if approved != independent_oracle:
            raise RuntimeError(f"Gate disagreement at row {i} ({df.object_id.iloc[i]})")
        # This routing is derived for an audit; only Release is decided by the
        # existing Python gate. Review/Withhold have not been executed by a workflow.
        routing = "Release" if approved else ("Withhold" if not s else "Review")
        count[routing] += 1
        results.append({
            "record_type": "offline_gate_replay",
            "object_id": str(df.object_id.iloc[i]),
            "model": str(df.model.iloc[i]),
            "split": "test", "prefix": 128,
            "confidence": c, "epistemic_uncertainty": u,
            "quality": qual, "source_verified": s,
            "release_authorized": approved,
            "derived_routing_not_executed": routing,
        })

    out.mkdir(parents=True, exist_ok=True)
    target = out / "gate_decisions.jsonl"
    with target.open("w", encoding="utf-8") as f:
        for row in results:
            f.write(json.dumps(row, allow_nan=False) + "\n")
    summary = {
        "evidence_type": "offline replay of saved held-out ensemble predictions through corrected Python release gate",
        "not_evidence_of": ["executed Python workflow transitions", "TLA+ trace conformance", "live deployment"],
        "input": str(src), "input_sha256": file_hash(src),
        "model": str(df.model.iloc[0]), "n_objects": len(df),
        "thresholds": thresholds, "release_authorized": count["Release"],
        "derived_review_count": count["Review"],
        "derived_withhold_count": count["Withhold"],
        "oracle_mismatches": 0, "trace_file": str(target),
    }
    (out / "gate_replay_summary.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("Completed OFFLINE GATE REPLAY (not full TLA+ conformance)")
    print(f"Model: {summary['model']}; test objects: {len(df)}")
    print(f"Authorized releases: {count['Release']}")
    print(f"Derived reviews: {count['Review']}; derived withholds: {count['Withhold']}")
    print("Decision-oracle disagreements: 0")
    print("Saved:", target)
    print("Saved:", out / "gate_replay_summary.json")


if __name__ == "__main__":
    main()
