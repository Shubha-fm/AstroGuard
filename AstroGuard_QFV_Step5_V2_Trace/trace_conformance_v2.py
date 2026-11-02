#!/usr/bin/env python3
"""Check Python before/after state traces against AstroGuardActor V2.

Input is JSON Lines, ONE record per real workflow transition (not predicted labels
and not model-checker-generated traces). First line: {"kind":"init","state":...}
Remaining lines: {"kind":"step","action":"Infer|Assess|Retry|ReloadModel|Release|Review|Withhold|Stutter",
"object":"o1" (except global action),"before":{...},"after":{...}}.
The checks enforce the concrete TLA+ guards and UNCHANGED conditions. Passing this
checker is observed trace conformance, NOT a formal refinement proof.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path

BOOL_FIELDS=('confidenceOK','uncertaintyOK','qualityOK','sourceOK')
MAP_FIELDS=('stage','assessedVersion',*BOOL_FIELDS,'retryCount','decision')
OBJECT_FIELDS=('stage','assessedVersion',*BOOL_FIELDS,'retryCount','decision')
GLOBALS=('modelVersion','actor')
STAGES={'Received','Inferencing','Assessed','Retry','Released','Review','Withheld'}
DECISIONS={'None','Release','Review','Withhold'}


def init_state(objects):
    return {'stage':{o:'Received' for o in objects},'modelVersion':1,
            'assessedVersion':{o:0 for o in objects},
            **{k:{o:False for o in objects} for k in BOOL_FIELDS},
            'retryCount':{o:0 for o in objects},'decision':{o:'None' for o in objects},
            'actor':'None'}


def validate_state(s,objects,max_version,max_retry):
    if set(s)!=(set(MAP_FIELDS)|set(GLOBALS)):raise ValueError('state has missing or extra variables')
    if not isinstance(s['modelVersion'],int) or type(s['modelVersion']) is bool or not 1<=s['modelVersion']<=max_version:
        raise ValueError('invalid modelVersion')
    if s['actor'] not in set(objects)|{'None','System'}:raise ValueError('invalid actor')
    for field in MAP_FIELDS:
        if not isinstance(s[field],dict) or set(s[field])!=set(objects):raise ValueError(f'{field}: object keys differ')
    for o in objects:
        if s['stage'][o] not in STAGES or s['decision'][o] not in DECISIONS:raise ValueError(f'invalid stage/decision for {o}')
        if type(s['assessedVersion'][o]) is not int or not 0<=s['assessedVersion'][o]<=max_version:raise ValueError('bad assessedVersion')
        if type(s['retryCount'][o]) is not int or not 0<=s['retryCount'][o]<=max_retry:raise ValueError('bad retryCount')
        for f in BOOL_FIELDS:
            if type(s[f][o]) is not bool:raise ValueError(f'{f}[{o}] not boolean')
        if s['decision'][o]=='Release' and not all(s[f][o] for f in BOOL_FIELDS):
            raise ValueError('NoUnsafeRelease invariant violated')


def expected_post(before,after,action,o,objects,max_version,max_retry):
    nxt=deepcopy(before)
    if action=='Stutter':
        if not all(before['stage'][x] in ('Released','Review','Withheld') for x in objects):
            raise ValueError('V2 TerminalStep guard false (not all terminal)')
        return nxt
    if action=='ReloadModel':
        if before['modelVersion']>=max_version:raise ValueError('ReloadModel guard false (maximum version)')
        nxt['modelVersion']+=1;nxt['actor']='System'
        return nxt
    if o not in objects:raise ValueError(f'unknown object: {o}')
    stage=before['stage'][o]
    nxt['actor']=o
    if action=='Infer':
        if stage not in ('Received','Retry'):raise ValueError('Infer guard false')
        nxt['stage'][o]='Inferencing';nxt['decision'][o]='None'
    elif action=='Assess':
        if stage!='Inferencing':raise ValueError('Assess guard false')
        nxt['stage'][o]='Assessed';nxt['assessedVersion'][o]=before['modelVersion']
        # These four choices are nondeterministic inputs in TLA+; use observed post-state.
        for key in BOOL_FIELDS:nxt[key][o]=after[key][o]
    elif action=='Retry':
        if stage not in ('Inferencing','Assessed') or before['retryCount'][o]>=max_retry:
            raise ValueError('Retry guard false')
        nxt['stage'][o]='Retry';nxt['retryCount'][o]+=1
        nxt['assessedVersion'][o]=0;nxt['decision'][o]='None'
    elif action=='Release':
        if stage!='Assessed' or before['assessedVersion'][o]!=before['modelVersion'] or not all(before[f][o] for f in BOOL_FIELDS):
            raise ValueError('Release guard false (unsafe/stale)')
        nxt['stage'][o]='Released';nxt['decision'][o]='Release'
    elif action=='Review':
        if stage!='Assessed' or not before['sourceOK'][o] or (before['assessedVersion'][o] == before['modelVersion'] and all(before[f][o] for f in ('confidenceOK','uncertaintyOK','qualityOK'))):
            raise ValueError('Review V2 guard false')
        nxt['stage'][o]='Review';nxt['decision'][o]='Review'
    elif action=='Withhold':
        if stage!='Assessed' or before['sourceOK'][o]:raise ValueError('Withhold guard false')
        nxt['stage'][o]='Withheld';nxt['decision'][o]='Withhold'
    else:raise ValueError(f'unsupported action: {action}')
    return nxt


def check_trace(lines,max_version=2,max_retry=1):
    if not lines:raise ValueError('empty trace')
    first=lines[0]
    if first.get('kind')!='init':raise ValueError('first record must be kind:init')
    initial=first['state'];objects=sorted(initial['stage'])
    if not objects:raise ValueError('no objects in trace')
    validate_state(initial,objects,max_version,max_retry)
    if initial!=init_state(objects):raise ValueError('initial state differs from TLA+ Init')
    previous=initial
    for number,rec in enumerate(lines[1:],start=2):
        try:
            if rec.get('kind')!='step':raise ValueError('not a step record')
            before=rec['before'];after=rec['after']
            validate_state(before,objects,max_version,max_retry)
            validate_state(after,objects,max_version,max_retry)
            if before!=previous:raise ValueError('before does not match preceding after-state')
            expected=expected_post(before,after,rec['action'],rec.get('object'),objects,max_version,max_retry)
            if after!=expected:
                differences=[f for f in expected if expected[f]!=after[f]]
                raise ValueError('TLA+ action transition mismatch in: '+', '.join(differences))
            previous=after
        except Exception as exc:raise ValueError(f'line {number}: {exc}') from exc
    return {'objects':len(objects),'transitions':len(lines)-1,'verdict':'PASS',
            'model':'AstroGuardActor V2',
            'caution':'Trace action agreement only for the supplied states; no formal refinement proof and no live-system claim'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--trace',required=True,help='Actual instrumented Python workflow JSONL file')
    p.add_argument('--out',default='RESULTS_60K/formal_verification/trace_conformance.json')
    p.add_argument('--max-version',type=int,default=2)
    p.add_argument('--max-retry',type=int,default=1)
    a=p.parse_args();path=Path(a.trace)
    records=[json.loads(s) for s in path.read_text(encoding='utf8').splitlines() if s.strip()]
    result=check_trace(records,max_version=a.max_version,max_retry=a.max_retry)
    result['input_trace']=str(path)
    out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
