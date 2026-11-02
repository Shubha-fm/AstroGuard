# AstroGuard Final Verification Report

Generated (UTC): 2026-11-02T17:33:54.915004+00:00

**Overall: INCOMPLETE**. PASS=14, FAIL=0, INCOMPLETE=9

| Check | Status | Detail |
|---|---|---|
| step5b_two_object_compile | PASS | exit=0; missing expected markers=[] |
| step5b_two_object | PASS | exit=0; missing expected markers=[] |
| step5c_retry_reload_compile | PASS | exit=0; missing expected markers=[] |
| step5c_retry_reload | PASS | exit=0; missing expected markers=[] |
| step5b_reference_trace | PASS | 1 init + 6 steps = 7 records; accounting consistent (not semantic proof) |
| step5c_reference_trace | PASS | 1 init + 10 steps = 11 records; accounting consistent (not semantic proof) |
| step5b_summary | PASS | Readable artifact (not independent semantic verification) |
| step5c_summary | PASS | Readable artifact (not independent semantic verification) |
| TLC_main | PASS | exit=0; missing expected markers=[] |
| TLC_FaultGate | PASS | Fault violation detected by TLC |
| TLC_FaultStale | PASS | Fault violation detected by TLC |
| TLC_FaultRetry | PASS | Fault violation detected by TLC |
| TLC_FaultMixup | PASS | Fault violation detected by TLC |
| deadlock_check_scope | INCOMPLETE | Deadlock checking disabled; TLC_main PASS does not prove deadlock freedom or liveness |
| production_workflow_execution | INCOMPLETE | No real production command supplied; cannot claim production validation |
| production_trace_syntax_only | INCOMPLETE | No production trace supplied |
| production_validator_report_integrity | INCOMPLETE | No independently generated production conformance report |
| production_trace_spec_conformance | INCOMPLETE | Production execution and validated trace evidence required |
| production_property_NoUnsafeRelease | INCOMPLETE | Not assessed from production execution and semantic adapter |
| production_property_FreshRelease | INCOMPLETE | Not assessed from production execution and semantic adapter |
| production_property_RetryInvalidatesAssessment | INCOMPLETE | Not assessed from production execution and semantic adapter |
| production_property_ObjectIsolation | INCOMPLETE | Not assessed from production execution and semantic adapter |
| core_source_manifest | PASS | Critical files hashed; not proof of repository completeness |

**Limitation:** Reference flows are not the existing production pipeline. A valid JSONL trace is not proof of trace equivalence or the four safety properties.
