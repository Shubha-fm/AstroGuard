#!/usr/bin/env python3
"""Exercise the corrected Python gate in a new *reference* finite-state workflow.

Inputs are saved held-out 60K ensemble gate-replay records; not live or actual
instrumented workflow transitions. Produces one trace for a Release object and
one for a Review object and checks both against the V2 TLA+ transition guards.
Does NOT prove conformance of a deployed Python release workflow.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from suite.latency import gate
from suite.common import config
from trace_conformance_v2 import init_state, check_trace, expected_post


def pick_examples(path):
    out={}
    with path.open(encoding='utf8') as f:
        for line in f:
            if not line.strip():continue
            rec=json.loads(line)
            if rec.get('record_type')!='offline_gate_replay':
                raise ValueError('Unexpected input record type')
            if rec.get('split')!='test' or rec.get('prefix')!=128:
                raise ValueError('Expected test set prefix=128 only')
            kind=rec.get('derived_routing_not_executed')
            if kind in ('Release','Review','Withhold') and kind not in out:
                out[kind]=rec
            if {'Release','Review','Withhold'}<=out.keys():break
    if 'Release' not in out or 'Review' not in out:
        raise ValueError('Need at least one Release and Review replay record')
    return out


def make_trace(rec, thresholds):
    c=float(rec['confidence']);q=float(rec['quality']);u=float(rec['epistemic_uncertainty'])
    if not all(math.isfinite(v) for v in (c,q,u)):
        raise ValueError('Non-finite numeric value')
    if type(rec['source_verified']) is not bool:
        raise ValueError('source_verified must be Boolean')
    s=rec['source_verified']
    ok=dict(confidenceOK=c>=thresholds['confidence'],
            uncertaintyOK=u<=thresholds['epistemic_uncertainty'],
            qualityOK=q>=thresholds['quality'],sourceOK=s)
    approved=gate(c,q,s,epistemic_uncertainty=u)
    if approved!=rec['release_authorized']:
        raise ValueError('Saved gate decision differs from corrected local implementation')
    routing='Release' if approved else 'Withhold' if not s else 'Review'
    if routing!=rec['derived_routing_not_executed']:
        raise ValueError('Derived routing differs from saved offline replay')

    objects=['o1']
    state=init_state(objects)
    records=[{'kind':'init','state':deepcopy(state)}]

    def emit(action, updates):
        nonlocal state
        before=deepcopy(state)
        updates(state)
        state['actor']='o1'
        after=deepcopy(state)
        records.append({'kind':'step','action':action,'object':'o1','before':before,'after':after})

    emit('Infer',lambda st:st['stage'].__setitem__('o1','Inferencing'))

    def assessed(st):
        st['stage']['o1']='Assessed'
        st['assessedVersion']['o1']=st['modelVersion']
        for k,v in ok.items():st[k]['o1']=v
    emit('Assess',assessed)

    def decide(st):
        st['stage']['o1']={'Release':'Released','Review':'Review','Withhold':'Withheld'}[routing]
        st['decision']['o1']=routing
    emit(routing,decide)
    result=check_trace(records,max_version=2,max_retry=1)
    return records,result,routing


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input',default='RESULTS_60K/formal_verification/python_gate_replay/gate_decisions.jsonl')
    ap.add_argument('--out',default='RESULTS_60K/formal_verification/python_trace_v2_reference')
    args=ap.parse_args()
    path=Path(args.input)
    if not path.is_file():ap.error(f'Missing gate replay records: {path}')
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    thresholds=config()['gate']; examples=pick_examples(path)
    results=[]
    for kind,rec in examples.items():
        records,report,routing=make_trace(rec,thresholds)
        trace=out/f'{kind.lower()}_reference_trace.jsonl'
        with trace.open('w',encoding='utf8') as f:
            for item in records:f.write(json.dumps(item,allow_nan=False)+'\n')
        results.append({'routing':routing,'object_id_sha256':hashlib.sha256(rec['object_id'].encode()).hexdigest(),
                        'steps':report['transitions'],'verdict':report['verdict'],'trace':str(trace)})
        print(f'{routing}: {report["verdict"]}; {report["transitions"]} reference workflow transitions')
    summary={'verdict':'PASS','evidence_type':'constructed reference Python workflow using offline replay input',
             'not_evidence_of':['conformance of an existing production workflow','live runtime traces','formal refinement proof'],
             'checker_model':'AstroGuardActor V2','results':results}
    target=out/'reference_trace_check_summary.json'
    target.write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print('Saved:',target)
    print('NOTE: These are constructed reference traces, NOT observed production workflow traces.')

if __name__=='__main__':main()
