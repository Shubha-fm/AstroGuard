#!/usr/bin/env python3
"""Step 5C: execute and verify retry/model-reload transitions of a NEW Python reference workflow.

Uses two REAL held-out RF ensemble gate inputs from Step 4, replays their saved
assessment values, and checks an executed, instrumented Python reference
workflow against the TLA+ V2 guards and unchanged-state requirements.

This is NOT execution tracing of the pre-existing AstroGuard pipeline, a live
ALeRCE experiment, or a mathematical proof of implementation refinement.
No original training/results files are overwritten.
"""
import argparse
from copy import deepcopy
from pathlib import Path
import hashlib
import json

from suite.common import config
from suite.latency import gate
from run_step5b_instrumented_two_object import InstrumentedWorkflow, choose_records, sha256
from trace_conformance_v2 import check_trace


class RetryReloadWorkflow(InstrumentedWorkflow):
    """Instrumented Python reference operations for TLA+ V2 Retry/ReloadModel."""
    def retry(self, obj):
        s = self.state
        if s['stage'][obj] not in ('Inferencing', 'Assessed') or s['retryCount'][obj] >= 1:
            raise ValueError('retry guard rejected')
        def update():
            s['stage'][obj] = 'Retry'
            s['retryCount'][obj] += 1
            s['assessedVersion'][obj] = 0
            s['decision'][obj] = 'None'
            s['actor'] = obj
        self.transition('Retry', obj, update)

    def reload_model(self):
        s = self.state
        if s['modelVersion'] >= 2:
            raise ValueError('reload guard rejected: maximum version')
        def update():
            s['modelVersion'] += 1
            s['actor'] = 'System'
        self.transition('ReloadModel', None, update)


def expect_invalid_mutation(events, action_name, mutator):
    altered = deepcopy(events)
    index = next(i for i, event in enumerate(altered)
                 if event.get('kind') == 'step' and event.get('action') == action_name)
    mutator(altered[index])
    try:
        check_trace(altered, max_version=2, max_retry=1)
    except ValueError:
        return True
    raise AssertionError(f'Mutated invalid {action_name} trace incorrectly accepted')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', default='RESULTS_60K/formal_verification/python_gate_replay/gate_decisions.jsonl')
    parser.add_argument('--out', default='RESULTS_60K/formal_verification/python_runtime_v2_retry_reload')
    parser.add_argument('--tla', default='tla_v2/AstroGuardActor.tla')
    args = parser.parse_args()
    src, out, tla = Path(args.input), Path(args.out), Path(args.tla)
    if not src.is_file():
        parser.error(f'Missing Step 4 gate replay: {src}')
    if not tla.is_file():
        parser.error(f'Missing TLA+ V2 source: {tla}')
    inputs = choose_records(src)
    limits = config()['gate']
    wf = RetryReloadWorkflow(['o1', 'o2'])

    # Work on two saved real 60K predictions, but execute reference operations anew.
    wf.infer('o1')
    wf.infer('o2')
    assessment_o1 = wf.assess('o1', inputs['Release'], limits)
    assessment_o2 = wf.assess('o2', inputs['Review'], limits)
    assert gate(assessment_o1[0], assessment_o1[1], assessment_o1[2],
                epistemic_uncertainty=assessment_o1[3]), 'o1 should be a safe gate approval'

    # A retry invalidates the old assessment and clears the decision.
    wf.retry('o2')
    retry_invalidated = (
        wf.state['stage']['o2'] == 'Retry' and
        wf.state['retryCount']['o2'] == 1 and
        wf.state['assessedVersion']['o2'] == 0 and
        wf.state['decision']['o2'] == 'None')
    if not retry_invalidated:
        raise AssertionError('retry failed to invalidate old assessment')

    # A global model update makes o1's otherwise acceptable assessment stale.
    wf.reload_model()
    stale_assessment = (wf.state['modelVersion'] == 2 and
                        wf.state['assessedVersion']['o1'] == 1)
    if not stale_assessment:
        raise AssertionError('expected o1 assessment to be outdated after reload')
    route_o1 = wf.route('o1', assessment_o1)
    if route_o1 != 'Review':
        raise AssertionError('stale approved assessment was not routed to review')

    # Re-infer/reassess o2 after its retry using the same saved replay inputs.
    # This is a replay, not an independently executed second model inference.
    wf.infer('o2')
    assessment_o2_again = wf.assess('o2', inputs['Review'], limits)
    route_o2 = wf.route('o2', assessment_o2_again)
    if route_o2 != 'Review':
        raise AssertionError('expected o2 review routing')

    result = check_trace(wf.events, max_version=2, max_retry=1)
    assert result['transitions'] == 10, result
    # Negative controls: checker must reject an invalid retry state, stale
    # release, and illegal mutation to a different object's state.
    mutations = {
        'retry_not_invalidated': expect_invalid_mutation(
            wf.events, 'Retry', lambda e: e['after']['assessedVersion'].__setitem__('o2', 1)),
        'stale_release_attempt': expect_invalid_mutation(
            wf.events, 'Review', lambda e: (e.__setitem__('action', 'Release'),
                e['after']['stage'].__setitem__('o1', 'Released'),
                e['after']['decision'].__setitem__('o1', 'Release'))),
        'cross_object_mutation': expect_invalid_mutation(
            wf.events, 'Infer', lambda e: e['after']['stage'].__setitem__('o2', 'Review')),
    }
    assert all(mutations.values())

    out.mkdir(parents=True, exist_ok=True)
    path = out / 'observed_reference_retry_reload_transitions.jsonl'
    with path.open('w', encoding='utf-8') as stream:
        for event in wf.events:
            stream.write(json.dumps(event, allow_nan=False) + '\n')
    result.update({
        'evidence_type': 'executed newly instrumented Python reference workflow',
        'scope_warning': 'Not pre-existing AstroGuard runtime traces, live deployment, or full TLA+ refinement',
        'replayed_inputs': 'one held-out authorized release and one held-out review, reused after retry',
        'input_file': str(src), 'input_sha256': sha256(src),
        'tla_v2': str(tla), 'tla_sha256': sha256(tla),
        'retry_invalidated_assessment': retry_invalidated,
        'model_reload_staled_assessment': stale_assessment,
        'stale_assessment_routed_to_review': route_o1 == 'Review',
        'routing': {'o1': route_o1, 'o2': route_o2},
        'invalid_mutations_rejected': mutations,
        'object_id_sha256': {
            'o1': hashlib.sha256(str(inputs['Release']['object_id']).encode()).hexdigest(),
            'o2': hashlib.sha256(str(inputs['Review']['object_id']).encode()).hexdigest()},
        'trace_file': str(path),
    })
    summary = out / 'retry_reload_trace_summary.json'
    summary.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(f"Retry/reload reference workflow: {result['verdict']}; {result['transitions']} transitions across {result['objects']} objects")
    print('Retry assessment invalidation: PASS')
    print('Stale assessment routed to review: PASS')
    print(f"Invalid-trace controls rejected: {sum(mutations.values())}/{len(mutations)}")
    print('Saved:', path)
    print('Saved:', summary)
    print('NOTE: Executed new Python reference workflow; NOT the pre-existing production pipeline')


if __name__ == '__main__':
    main()
