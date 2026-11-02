# AstroGuard

**Machine-learning experiments and TLA+-based formal verification for astronomical-object analysis workflows.**

AstroGuard is a research project combining astronomical-object classification experiments, decision-gating logic, TLA+ specifications, TLC model checking, fault-injection tests, and Python reference workflows.

## Project components

| Path | Description |
| --- | --- |
| `suite/` | Machine-learning models and experiment utilities |
| `tla/` | TLA+ specifications, TLC configurations, and fault-injection models |
| `run_18k.py`, `run_60k.py` | Experimental workflows |
| `run_large.py` | Large-scale experiment runner |
| `run_step5b_instrumented_two_object.py` | Two-object Python reference workflow |
| `run_step5c_retry_reload.py` | Retry/reload Python reference workflow |
| `trace_conformance_v2.py` | Reference trace-checking utility |
| `requirements.txt` | Python dependencies |
| `requirements-alerce.txt`, `requirements-quantum.txt` | Optional experiment dependencies |

## Installation

Use Python 3.11. TLC checks also require Java and the TLA+ tools JAR.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Install optional dependencies for the corresponding experiments when needed:

```bash
python -m pip install -r requirements-alerce.txt
python -m pip install -r requirements-quantum.txt
```

## Completed reference verification

From the repository root, run:

```bash
python run_step5b_instrumented_two_object.py
python run_step5c_retry_reload.py
```

The following results were reported from the completed tests on **2 November 2026**:

| Test | Observed result |
| --- | --- |
| Two-object reference workflow | PASS: 6 transitions across 2 objects |
| Retry/reload reference workflow | PASS: 10 transitions across 2 objects |
| Retry assessment invalidation | PASS |
| Stale assessment routed to review | PASS |
| Invalid-trace controls | 3/3 rejected |
| Main TLA+ model | TLC PASS under the configured checks |
| FaultGate | Expected TLC violation detected |
| FaultStale | Expected TLC violation detected |
| FaultRetry | Expected TLC violation detected |
| FaultMixup | Expected TLC violation detected |
| Trace record accounting | PASS: initial-state record distinguished from transitions |

The recorded JSONL traces comprise one `init` record plus six or ten `step` records, respectively.

### Formal properties studied

- `NoUnsafeRelease`
- `FreshRelease`
- `RetryInvalidatesAssessment`
- `ObjectIsolation`

**Verification scope:** These results concern the specified TLA+ model and instrumented Python reference workflows. The main TLC configuration uses `CHECK_DEADLOCK FALSE`; the reported pass concerns the enabled model checks and does not establish deadlock freedom. No claim of verification of a production implementation is made.

## Experiments and reproducibility

The project includes code and recorded outputs for astronomical-data preparation, model training, prediction, evaluation, and formal checks across 18K and 60K experiment workflows. Reproduction depends on the relevant input datasets, configurations, package versions, and run settings.

The full experiment logs, datasets eligible for redistribution, and model checkpoints are being organized as a separate Zenodo research archive. A DOI will be added after publication.

## Author

**Shubha Chakraborty**  
Department of Computer Science, The University of Burdwan, India  
ORCID: [0009-0000-5015-0478](https://orcid.org/0009-0000-5015-0478)

## Citation and license

A version-specific citation will be provided when the Zenodo record is published. Please check the repository license and applicable third-party data terms before reuse.
