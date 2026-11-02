#!/usr/bin/env python3
"""Execute an instrumented NEW Python reference workflow on two real 60K held-out gate inputs.

This is an executed Python workflow with observed before/after action states, unlike
constructed reference traces. It is NOT the existing production/runtime pipeline,
not a live ALeRCE experiment, and not a TLA+ refinement proof.
"""
import argparse
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import math

from suite.common import config
from suite.latency import gate
from trace_conformance_v2 import init_state, check_trace

FLAGS = ("confidenceOK", "uncertaintyOK", "qualityOK", "sourceOK")


def choose_records(path):
    found = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            x = json.loads(line)
            if x.get("record_type") != "offline_gate_replay" or x.get("split") != "test" or x.get("prefix") != 128:
                raise ValueError("Unexpected input: require saved 60K held-out prefix-128 gate replay")
            routing = x.get("derived_routing_not_executed")
            if routing in ("Release", "Review") and routing not in found:
                found[routing] = x
            if "Release" in found and "Review" in found:
                return found
    raise ValueError("Need at least one Release and one Review in saved replay")


class InstrumentedWorkflow:
    """New, observable Python reference implementation of V2 transition guards."""
    def __init__(self, objects):
        self.state = init_state(objects)
        self.events = [{"kind": "init", "state": deepcopy(self.state)}]

    def transition(self, action, obj, update):
        before = deepcopy(self.state)
        update()
        self.events.append({"kind": "step", "action": action, "object": obj,
                            "before": before, "after": deepcopy(self.state)})

    def infer(self, obj):
        if self.state["stage"][obj] not in ("Received", "Retry"):
            raise ValueError("infer guard rejected")
        def update():
            self.state["stage"][obj] = "Inferencing"
            self.state["decision"][obj] = "None"
            self.state["actor"] = obj
        self.transition("Infer", obj, update)

    def assess(self, obj, input_record, limits):
        if self.state["stage"][obj] != "Inferencing":
            raise ValueError("assess guard rejected")
        c = float(input_record["confidence"])
        u = float(input_record["epistemic_uncertainty"])
        q = float(input_record["quality"])
        if not all(math.isfinite(v) for v in (c, u, q)):
            raise ValueError("nonfinite assessment input")
        source = input_record["source_verified"]
        if type(source) is not bool:
            raise TypeError("source_verified must be boolean")
        flags = {"confidenceOK": c >= limits["confidence"],
                 "uncertaintyOK": u <= limits["epistemic_uncertainty"],
                 "qualityOK": q >= limits["quality"],
                 "sourceOK": source}
        def update():
            self.state["stage"][obj] = "Assessed"
            self.state["assessedVersion"][obj] = self.state["modelVersion"]
            for flag in FLAGS:
                self.state[flag][obj] = bool(flags[flag])
            self.state["actor"] = obj
        self.transition("Assess", obj, update)
        return c, q, source, u

    def route(self, obj, assessment):
        if self.state["stage"][obj] != "Assessed":
            raise ValueError("route guard rejected")
        c, q, source, uncertainty = assessment
        approved = gate(c, q, source, epistemic_uncertainty=uncertainty)
        # Do NOT let an otherwise acceptable but outdated assessment be released.
        fresh = self.state["assessedVersion"][obj] == self.state["modelVersion"]
        decision = "Release" if approved and fresh else ("Withhold" if not source else "Review")
        stage = {"Release": "Released", "Review": "Review", "Withhold": "Withheld"}[decision]
        def update():
            self.state["stage"][obj] = stage
            self.state["decision"][obj] = decision
            self.state["actor"] = obj
        self.transition(decision, obj, update)
        return decision


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", default="RESULTS_60K/formal_verification/python_gate_replay/gate_decisions.jsonl")
    p.add_argument("--out", default="RESULTS_60K/formal_verification/python_runtime_v2_two_object")
    p.add_argument("--tla", default="tla_v2/AstroGuardActor.tla")
    args = p.parse_args()
    src, target, tla = Path(args.input), Path(args.out), Path(args.tla)
    if not src.is_file():
        p.error(f"Missing input replay file: {src}")
    if not tla.is_file():
        p.error(f"Missing revised source: {tla}")
    records = choose_records(src)
    wf = InstrumentedWorkflow(["o1", "o2"])
    # Interleave both object workflows, rather than inventing one-object traces.
    wf.infer("o1")
    wf.infer("o2")
    inputs = {"o1": records["Release"], "o2": records["Review"]}
    limits = config()["gate"]
    a2 = wf.assess("o2", inputs["o2"], limits)
    a1 = wf.assess("o1", inputs["o1"], limits)
    d1 = wf.route("o1", a1)
    d2 = wf.route("o2", a2)
    if (d1, d2) != ("Release", "Review"):
        raise AssertionError("Executed workflow disagrees with expected release/review routing")
    if d1 != records["Release"]["derived_routing_not_executed"] or d2 != records["Review"]["derived_routing_not_executed"]:
        raise AssertionError("Executed workflow differs from saved replay")
    # Independent checker sees the observed state snapshots, not the runner's rules.
    result = check_trace(wf.events, max_version=2, max_retry=1)
    result.update({"evidence_type": "executed, newly instrumented Python reference workflow",
                   "scope_warning": "Not the existing 60K pipeline's stateful workflow, live broker execution, or refinement proof",
                   "input": str(src), "input_sha256": sha256(src),
                   "tla_v2": str(tla), "tla_sha256": sha256(tla),
                   "routing": {"o1": d1, "o2": d2},
                   "object_id_sha256": {o: hashlib.sha256(str(x["object_id"]).encode()).hexdigest()
                                        for o,x in inputs.items()}})
    target.mkdir(parents=True, exist_ok=True)
    trace = target / "observed_python_reference_transitions.jsonl"
    with trace.open("w", encoding="utf-8") as fh:
        for event in wf.events:
            fh.write(json.dumps(event, allow_nan=False) + "\n")
    result["trace_file"] = str(trace)
    summary = target / "two_object_trace_summary.json"
    summary.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Observed reference workflow: {result['verdict']}; {result['transitions']} transitions across {result['objects']} objects")
    print(f"Routing: o1={d1}, o2={d2}")
    print("Saved:", trace)
    print("Saved:", summary)
    print("NOTE: Executed new instrumented reference workflow, NOT the pre-existing production workflow")


if __name__ == "__main__":
    main()
