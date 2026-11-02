#!/usr/bin/env python3
"""AstroGuard single-command final verification runner v4 (Python 3.9+).

Run from the AstroGuard project root. No external Python packages required.
A missing verification stage is INCOMPLETE, never a silent PASS.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
import traceback

ROOT = Path.cwd().resolve()
CHECK_NAMES = ("NoUnsafeRelease", "FreshRelease",
               "RetryInvalidatesAssessment", "ObjectIsolation")
STEPS = [
    ("step5b_two_object", "run_step5b_instrumented_two_object.py",
     ("Observed reference workflow: PASS",)),
    ("step5c_retry_reload", "run_step5c_retry_reload.py",
     ("Retry/reload reference workflow: PASS",
      "Retry assessment invalidation: PASS",
      "Stale assessment routed to review: PASS",
      "Invalid-trace controls rejected: 3/3")),
]

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def stamp(name):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)

def record(name, status, detail, **kwargs):
    x = dict(name=name, status=status, detail=detail)
    x.update(kwargs)
    RESULTS.append(x)
    print(f"[{status}] {name}: {detail}", flush=True)

def run_command(name, cmd, cwd, timeout, required=()):
    log = OUT / (stamp(name) + ".log")
    t = time.monotonic()
    try:
        with log.open("w", encoding="utf-8") as f:
            f.write("Command: " + shlex.join([str(c) for c in cmd]) + "\n")
            f.write("Working directory: " + str(cwd) + "\n\n")
            f.flush()
            p = subprocess.run(cmd, cwd=str(cwd), stdout=f, stderr=subprocess.STDOUT,
                               text=True, timeout=timeout, check=False)
        output = log.read_text(encoding="utf-8", errors="replace")
        missing = [phrase for phrase in required if phrase not in output]
        ok = p.returncode == 0 and not missing
        record(name, "PASS" if ok else "FAIL",
               f"exit={p.returncode}; missing expected markers={missing}",
               command=cmd, log=str(log), seconds=round(time.monotonic()-t, 2))
        return ok, output
    except subprocess.TimeoutExpired:
        record(name, "FAIL", f"Timed out after {timeout}s", command=cmd, log=str(log))
    except Exception as exc:
        record(name, "FAIL", f"{type(exc).__name__}: {exc}", command=cmd, log=str(log))
    return False, ""

def parse_jsonl(path):
    count = 0
    object_ids = set()
    observed_fields = set()
    with path.open("r", encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            data = json.loads(line)
            if not isinstance(data, dict):
                raise ValueError(f"line {n} is not a JSON object")
            count += 1
            observed_fields.update(data.keys())
            for key in ("object_id", "object", "obj_id", "oid"):
                if key in data and isinstance(data[key], (str, int)):
                    object_ids.add(str(data[key]))
                    break
    if count == 0:
        raise ValueError("empty trace")
    return {"transitions": count, "distinct_object_ids_if_present": len(object_ids),
            "observed_fields": sorted(observed_fields)}

def trace_check(name, file, expected_count=None, min_objects=None, required=True):
    if not file.is_file():
        record(name, "FAIL" if required else "INCOMPLETE", f"Missing trace: {file}")
        return
    try:
        info = parse_jsonl(file)
        issues = []
        if expected_count is not None and info["transitions"] != expected_count:
            issues.append(f"reference workflow reported {expected_count} transitions; "
                          f"JSONL has {info['transitions']} records. "
                          "Inspect the extra record before claiming count equivalence")
        if min_objects is not None and info["distinct_object_ids_if_present"] < min_objects:
            issues.append("cannot confirm two object IDs from known JSONL fields")
        status = "INCOMPLETE" if issues else "PASS"
        # Inspect extra rows explicitly. Do not assume that a 7th/11th row is an initial state.
        if expected_count is not None and info["transitions"] == expected_count + 1:
            with file.open(encoding="utf-8") as fh:
                rows = [json.loads(line) for line in fh if line.strip()]
            sample = [{"row": i+1, "fields": list(row), "type": row.get("type", row.get("event", row.get("kind", None)))}
                      for i, row in enumerate(rows) if i in (0, len(rows)-1)]
            info["extra_row_diagnostic"] = sample
        record(name, status,
               "; ".join(issues) or f"Valid JSONL: {info['transitions']} records; "
               "count and IDs consistent (not proof of safety)",
               path=str(file), sha256=sha256(file), data=info)
    except Exception as exc:
        record(name, "FAIL", f"{type(exc).__name__}: {exc}", path=str(file))

def find_model(module_name, cfg_name):
    """Find requested model without mistaking archived results for source models."""
    def candidates(name):
        out = []
        if not name:
            return out
        direct = ROOT / name
        if direct.is_file():
            return [direct.resolve()]
        for path in ROOT.rglob(Path(name).name):
            rel = path.relative_to(ROOT)
            if any(part.startswith("RESULTS") or part in
                   (".venv", ".git", "__pycache__", "node_modules") for part in rel.parts):
                continue
            if path.is_file():
                out.append(path.resolve())
        return sorted(set(out))
    modules = candidates(module_name) if module_name else []
    if not modules:
        modules = [p for p in ROOT.rglob("*.tla")
                   if not any(q.startswith("RESULTS") or q in
                              (".venv", ".git", "__pycache__", "node_modules")
                              for q in p.relative_to(ROOT).parts)]
    pairs = []
    for m in modules:
        cfgs = candidates(cfg_name) if cfg_name else [m.with_suffix(".cfg")]
        for c in cfgs:
            if c.is_file() and c.parent == m.parent:
                pairs.append((m,c))
    return sorted(set(pairs))

def file_check(name, file):
    if file.is_file():
        try:
            if file.suffix == ".json":
                with file.open(encoding="utf-8") as f:
                    json.load(f)
            record(name, "PASS", "Readable artifact (not independent semantic verification)",
                   path=str(file), sha256=sha256(file))
        except Exception as exc:
            record(name, "FAIL", f"Invalid artifact: {exc}", path=str(file))
    else:
        record(name, "INCOMPLETE", f"Artifact not found: {file}")

def main():
    global ROOT, OUT, RESULTS
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--tlc-module", help="TLA+ module file to model-check, e.g. AstroGuardActor.tla")
    ap.add_argument("--tlc-config", help="TLC config file, e.g. AstroGuardActor.cfg")
    ap.add_argument("--tlc-timeout", type=int, default=3600)
    ap.add_argument("--production-cmd", help="EXPLICIT command invoking the REAL production flow")
    ap.add_argument("--production-trace", type=Path,
                    help="JSONL events emitted by the production workflow, not a reference simulation")
    ap.add_argument("--fault-timeout", type=int, default=300,
                    help="Seconds allowed for each fault-injection model")
    ap.add_argument("--skip-fault-models", action="store_true")
    ap.add_argument("--production-validator-cmd", help="Independent trusted production trace validator command; must output a JSON report")
    ap.add_argument("--production-validator-report", type=Path, help="JSON report from validator containing property statuses and trace conformance")
    ap.add_argument("--skip-reference", action="store_true",
                    help="Do not rerun reference workflows (reports INCOMPLETE)")
    args = ap.parse_args()
    ROOT = args.root.resolve()
    OUT = ROOT / "RESULTS_60K" / "FINAL_ALL_CHECKS"
    OUT.mkdir(parents=True, exist_ok=True)
    RESULTS = []
    print("AstroGuard final suite v4:", now())
    print("Project:", ROOT)
    print("Outputs:", OUT)
    print("NOTE: Reference workflow success is NOT production verification.")
    print()
    for name, filename, markers in STEPS:
        src = ROOT / filename
        if not src.is_file():
            record(name, "INCOMPLETE", f"Script unavailable: {src}")
            continue
        if args.skip_reference:
            record(name, "INCOMPLETE", "Not executed: --skip-reference")
            continue
        run_command(name + "_compile", [sys.executable, "-m", "py_compile", str(src)],
                    ROOT, args.timeout)
        run_command(name, [sys.executable, str(src)], ROOT, args.timeout, markers)

    traces = [
        ("step5b_reference_trace",
         ROOT / "RESULTS_60K/formal_verification/python_runtime_v2_two_object"
                "/observed_python_reference_transitions.jsonl", 6, 2),
        ("step5c_reference_trace",
         ROOT / "RESULTS_60K/formal_verification/python_runtime_v2_retry_reload"
                "/observed_reference_retry_reload_transitions.jsonl", 10, 2),
    ]
    for name, path, expected, objects in traces:
        # Object-count evidence depends on trace schema, so check separately.
        trace_check(name, path, expected_count=expected, min_objects=objects, required=False)

    # Print concrete record details to enable diagnosis, not an unsupported assumption
    # that a seventh / eleventh JSONL row is an initial state.
    diagnostics = []
    for tag, path, expected, _ in traces:
        if not path.is_file():
            continue
        try:
            rows = [json.loads(t) for t in path.read_text(encoding="utf-8").splitlines() if t.strip()]
            signatures = []
            for ix, row in enumerate(rows):
                signatures.append({"row": ix + 1,
                                   "keys": sorted(row.keys()),
                                   "event": {k: row[k] for k in ("event", "type", "action", "kind", "transition", "is_initial", "initial") if k in row},
                                   "sha256_canonical_row": hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()})
            diagnostics.append({"trace": tag, "expected_reported_transitions": expected,
                                "jsonl_records": len(rows), "rows": signatures,
                                "note": "Event-schema evidence is needed to decide whether one record is an initial state."})
        except Exception as exc:
            diagnostics.append({"trace": tag, "error": str(exc)})
    (OUT / "trace_record_diagnostics.json").write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")

    file_check("step5b_summary",
               ROOT / "RESULTS_60K/formal_verification/python_runtime_v2_two_object"
                      "/two_object_trace_summary.json")
    file_check("step5c_summary",
               ROOT / "RESULTS_60K/formal_verification/python_runtime_v2_retry_reload"
                      "/retry_reload_trace_summary.json")

    # The canonical model is known from this project's folder structure.
    # Fault models are expected to trigger an error, but should not be marked PASS
    # unless TLC identifies an invariant/property violation (not parsing/runtime errors).
    jar = ROOT / "tla2tools.jar"
    java = shutil.which("java")
    if args.tlc_module:
        pairs = find_model(args.tlc_module, args.tlc_config)
    else:
        pairs = find_model("tla/AstroGuardActor.tla", "tla/AstroGuardActor.cfg")
    if len(pairs) != 1:
        record("TLC_main", "INCOMPLETE", "Canonical model/config not uniquely available; "
               f"matched {len(pairs)} pairs")
    elif not (jar.is_file() and java):
        record("TLC_main", "INCOMPLETE", f"Java={bool(java)}, jar={jar.is_file()}")
    else:
        module, cfg = pairs[0]
        cmd = [java, "-cp", str(jar), "tlc2.TLC", "-workers", "1",
               "-config", cfg.name, module.name]
        ok, output = run_command("TLC_main", cmd, module.parent, args.tlc_timeout)
        if ok and not re.search(r"Model checking completed\.\s*No error (?:has been )?found", output, re.I):
            RESULTS[-1]["status"] = "INCOMPLETE"
            RESULTS[-1]["detail"] = "Exit 0 but no recognized TLC clean-completion marker; inspect log"
            print("[INCOMPLETE] TLC_main: clean completion not established", flush=True)

    if args.skip_fault_models:
        record("TLC_fault_models", "INCOMPLETE", "Skipped by request")
    elif not jar.is_file() or not java:
        record("TLC_fault_models", "INCOMPLETE", "Java and/or tla2tools.jar not available")
    else:
        for fault in ("FaultGate", "FaultStale", "FaultRetry", "FaultMixup"):
            pairs = find_model("tla/"+fault+".tla", "tla/"+fault+".cfg")
            if len(pairs) != 1:
                record("TLC_"+fault, "INCOMPLETE", "Fault model/config unavailable or ambiguous")
                continue
            module, cfg = pairs[0]
            cmd = [java, "-cp", str(jar), "tlc2.TLC", "-workers", "1",
                   "-config", cfg.name, module.name]
            # Fault models are negative controls: expected nonzero exit may still be correct.
            log = OUT / ("TLC_"+fault+".log")
            try:
                with log.open("w", encoding="utf-8") as f:
                    f.write("Command: "+shlex.join(cmd)+"\n")
                    f.flush()
                    result = subprocess.run(cmd, cwd=str(module.parent), stdout=f,
                                            stderr=subprocess.STDOUT, timeout=args.fault_timeout,
                                            check=False)
                output = log.read_text(encoding="utf-8", errors="replace")
                violation = bool(re.search(r"Invariant .* is violated|Temporal property .* is violated|"
                                           r"Property .* is violated|Error: Invariant|"
                                           r"Error: Temporal property", output, re.I))
                clean = bool(re.search(r"Model checking completed\.\s*No error", output, re.I))
                status = "PASS" if violation else "FAIL" if clean else "INCOMPLETE"
                record("TLC_"+fault, status,
                       "Fault violation detected by TLC" if violation else
                       "Fault model finished without a reported violation" if clean else
                       "No recognizable violation; review error/timeout and log",
                       log=str(log), returncode=result.returncode)
            except subprocess.TimeoutExpired:
                record("TLC_"+fault, "INCOMPLETE", f"Timed out at {args.fault_timeout}s", log=str(log))
            except Exception as exc:
                record("TLC_"+fault, "FAIL", f"Execution error: {exc}", log=str(log))

    # Record exact model/checker configuration; deadlock suppression is a documented limitation.
    main_cfg = ROOT / "tla" / "AstroGuardActor.cfg"
    if main_cfg.is_file():
        config_text = main_cfg.read_text(encoding="utf-8", errors="replace")
        disabled = bool(re.search(r"(?m)^\s*CHECK_DEADLOCK\s+FALSE\s*$", config_text))
        record("deadlock_check_scope", "INCOMPLETE" if disabled else "PASS",
               "Deadlock checking disabled; TLC_main PASS does not prove deadlock freedom or liveness" if disabled
               else "No explicit CHECK_DEADLOCK FALSE in primary config; confirm TLC version and defaults",
               config_sha256=sha256(main_cfg))
    else:
        record("deadlock_check_scope", "INCOMPLETE", "Missing main TLC config")

    if args.production_cmd:
        # Deliberately no shell=True; paths/flags should be quoted in the argument.
        try:
            cmd = shlex.split(args.production_cmd)
            if not cmd:
                raise ValueError("empty production command")
            run_command("production_workflow_execution", cmd, ROOT, args.tlc_timeout)
        except Exception as exc:
            record("production_workflow_execution", "FAIL", str(exc))
    else:
        record("production_workflow_execution", "INCOMPLETE",
               "No real production command supplied; cannot claim production validation")
    if args.production_trace:
        trace_path = args.production_trace
        if not trace_path.is_absolute():
            trace_path = ROOT / trace_path
        trace_check("production_trace_syntax_only", trace_path, min_objects=2)
    else:
        record("production_trace_syntax_only", "INCOMPLETE", "No production trace supplied")

    # Never accept a passing workflow or mere JSONL parsing as proof of TLA+ trace refinement.
    # This hook accepts a *separate* purpose-built validator with a recorded report.
    if args.production_validator_cmd:
        try:
            cmd = shlex.split(args.production_validator_cmd)
            if not cmd:
                raise ValueError("empty validator command")
            run_command("production_validator_execution", cmd, ROOT, args.tlc_timeout)
        except Exception as exc:
            record("production_validator_execution", "FAIL", str(exc))
    report_path = args.production_validator_report
    validated = None
    if report_path:
        if not report_path.is_absolute():
            report_path = ROOT / report_path
        try:
            validated = json.loads(report_path.read_text(encoding="utf-8"))
            if not isinstance(validated, dict):
                raise ValueError("validator report must be an object")
            if validated.get("source") != "production" or not validated.get("validator") or not validated.get("trace_sha256"):
                raise ValueError("report missing production provenance, validator name, or trace SHA256")
            if not args.production_trace or not trace_path.is_file() or validated["trace_sha256"] != sha256(trace_path):
                raise ValueError("production trace hash missing or does not match report")
            if validated.get("conformance") not in ("PASS", "FAIL"):
                raise ValueError("explicit conformance PASS/FAIL required")
            props = validated.get("properties", {})
            if not all(props.get(k) in ("PASS", "FAIL") for k in CHECK_NAMES):
                raise ValueError("must report each of the four properties")
            record("production_validator_report_integrity", "PASS", "Evidence fields and trace digest match; validator implementation still requires review",
                   report=str(report_path), sha256=sha256(report_path))
        except Exception as exc:
            validated = None
            record("production_validator_report_integrity", "FAIL", str(exc))
    else:
        record("production_validator_report_integrity", "INCOMPLETE", "No independently generated production conformance report")
    # Separate declarations mean an unrun production integration cannot become verified
    # merely by supplying a syntactically valid JSON report.
    production_ran = any(r["name"] == "production_workflow_execution" and r["status"] == "PASS" for r in RESULTS)
    integrity_ok = any(r["name"] == "production_validator_report_integrity" and r["status"] == "PASS" for r in RESULTS)
    can_use = production_ran and integrity_ok and validated is not None
    record("production_trace_spec_conformance", validated["conformance"] if can_use else "INCOMPLETE",
           "Independent validator report (review validator semantics separately)" if can_use else "Production execution and validated trace evidence required")
    for prop in CHECK_NAMES:
        record("production_property_" + prop, validated["properties"][prop] if can_use else "INCOMPLETE",
               "Production validator's reported result; independent audit of validator still needed" if can_use else "Not assessed from production execution and semantic adapter")

    # Reproducibility manifest. These are inventory checks, not automatic claims of scientific validity.
    critical = [ROOT / "tla" / "AstroGuardActor.tla", ROOT / "tla" / "AstroGuardActor.cfg",
                ROOT / "run_step5b_instrumented_two_object.py", ROOT / "run_step5c_retry_reload.py",
                ROOT / "tla2tools.jar"]
    manifest = {"created_utc": now(), "files": []}
    for path in critical:
        manifest["files"].append({"path": str(path.relative_to(ROOT)), "exists": path.is_file(),
                                  "sha256": sha256(path) if path.is_file() else None})
    (OUT / "source_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    record("core_source_manifest", "PASS" if all(f["exists"] for f in manifest["files"]) else "INCOMPLETE",
           "Critical files hashed; not proof of repository completeness" if all(f["exists"] for f in manifest["files"]) else "One or more critical files missing")
    # Submission gate stays incomplete when production is not validated or reference count unresolved.
    blockers = [r["name"] for r in RESULTS if r["status"] != "PASS"]
    (OUT / "submission_blockers.json").write_text(json.dumps({"blockers": blockers,
                 "notes": ["Do not claim deadlock freedom with CHECK_DEADLOCK FALSE",
                           "Reference trace extra row must be classified from actual event schema",
                           "Production trace validator must be independently reviewed",
                           "Scientific claims, split leakage, statistics, DOI references and manuscript must be checked against source data"]}, indent=2), encoding="utf-8")

    counts = {s: sum(r["status"] == s for r in RESULTS)
              for s in ("PASS", "FAIL", "INCOMPLETE")}
    overall = "FAIL" if counts["FAIL"] else ("INCOMPLETE" if counts["INCOMPLETE"] else "PASS")
    summary = {"generated_utc": now(), "root": str(ROOT), "overall": overall,
               "counts": counts, "checks": RESULTS,
               "disclaimer": "Passing scripted reference workflows does not establish production conformance."}
    report = OUT / "final_report.json"
    report.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    md = [
        "# AstroGuard Final Verification Report", "",
        f"Generated (UTC): {summary['generated_utc']}", "",
        f"**Overall: {overall}**. PASS={counts['PASS']}, FAIL={counts['FAIL']}, "
        f"INCOMPLETE={counts['INCOMPLETE']}", "",
        "| Check | Status | Detail |", "|---|---|---|"
    ]
    for r in RESULTS:
        detail = str(r["detail"]).replace("|", "\\|").replace("\n", " ")
        md.append(f"| {r['name']} | {r['status']} | {detail} |")
    md.extend(["", "**Limitation:** Reference flows are not the existing production pipeline. "
               "A valid JSONL trace is not proof of trace equivalence or the four safety properties."])
    (OUT / "final_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\nFINAL:", overall, counts)
    print("Reports:", report, "and", OUT / "final_report.md")
    print("Also:", OUT / "trace_record_diagnostics.json", OUT / "submission_blockers.json")
    return 1 if overall == "FAIL" else (2 if overall == "INCOMPLETE" else 0)

if __name__ == "__main__":
    sys.exit(main())
