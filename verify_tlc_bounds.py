#!/usr/bin/env python3
"""Run genuine TLC on AstroGuardActor at 1-3 object bounds, with deadlock ON/OFF.

Does not change source TLA+ or overwrite the 18K/60K model checks. Requires a
real TLC jar (the existing local tla2tools.jar); no results are fabricated.
"""
import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path

PROPERTIES='''SPECIFICATION Spec
INVARIANTS
  TypeOK
  NoUnsafeRelease
PROPERTIES
  FreshRelease
  RetryInvalidatesAssessment
  ObjectIsolation
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jar',default='tla2tools.jar')
    parser.add_argument('--tla',default='tla/AstroGuardActor.tla')
    parser.add_argument('--out',default='RESULTS_60K/formal_verification/extended')
    parser.add_argument('--objects',nargs='+',type=int,default=[1,2,3])
    parser.add_argument('--timeout',type=int,default=900)
    parser.add_argument('--deadlock',choices=['enabled','disabled'],default='enabled')
    parser.add_argument('--max-version',type=int,default=2)
    parser.add_argument('--max-retry',type=int,default=1)
    args=parser.parse_args()
    jar=Path(args.jar).resolve();tla=Path(args.tla).resolve();out=Path(args.out).resolve()
    if not jar.is_file():parser.error(f'Missing real TLC JAR: {jar}')
    if not tla.is_file():parser.error(f'Missing source TLA+: {tla}')
    if args.timeout<1 or any(n<1 or n>5 for n in args.objects):parser.error('timeout>=1; objects between 1 and 5')
    if args.max_version<1 or args.max_retry<0:parser.error('invalid bounds')
    out.mkdir(parents=True,exist_ok=True)
    results=[]
    for n in args.objects:
        name=f'objects_{n}_deadlock_{args.deadlock}'
        cfg='CONSTANTS\n  Objects = {'+', '.join(f'o{i}' for i in range(1,n+1))+f'}}\n  MaxVersion = {args.max_version}\n  MaxRetry = {args.max_retry}\n'+PROPERTIES
        (out/f'{name}.cfg').write_text(cfg,encoding='utf-8')
        with tempfile.TemporaryDirectory(prefix='astroguard_tlc_') as folder:
            temp=Path(folder)
            (temp/'AstroGuardActor.tla').write_bytes(tla.read_bytes())
            (temp/'AstroGuardActor.cfg').write_text(cfg,encoding='utf-8')
            cmd=['java','-cp',str(jar),'tlc2.TLC','-workers','1']
            if args.deadlock=='disabled':cmd+=['-deadlock']
            cmd+=['-config','AstroGuardActor.cfg','AstroGuardActor.tla']
            begin=time.perf_counter();rc=None
            try:
                run=subprocess.run(cmd,cwd=temp,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                   encoding='utf-8',errors='replace',timeout=args.timeout,check=False)
                rc=run.returncode;log=run.stdout
                verdict='PASS' if rc==0 and 'Model checking completed. No error has been found.' in log else 'ERROR_OR_VIOLATION'
            except subprocess.TimeoutExpired as ex:
                log=(ex.stdout or b'')
                if isinstance(log,bytes):log=log.decode('utf-8','replace')
                log+='\nTIMEOUT: run exceeded '+str(args.timeout)+' seconds\n'
                verdict='TIMEOUT'
            (out/f'{name}.log').write_text('$ '+' '.join(cmd)+'\n'+log,encoding='utf-8')
        # Match ONLY the final standalone TLC summary line, not Progress(...) logs.
        final = re.search(
            r'(?m)^\s*(\d[\d,]*) states generated, '
            r'(\d[\d,]*) distinct states found, '
            r'(\d[\d,]*) states left on queue\.\s*$', log)
        def final_count(group):
            return int(final.group(group).replace(',', '')) if final else None
        if verdict == 'PASS' and (final is None or final_count(3) != 0):
            verdict = 'INCOMPLETE_FINAL_SUMMARY'
        result={'objects':n,'deadlock_check':args.deadlock,'verdict':verdict,'return_code':rc,
                'generated_states':final_count(1),
                'distinct_states':final_count(2),
                'states_left_on_queue':final_count(3),
                'elapsed_seconds':round(time.perf_counter()-begin,3),
                'log':f'{name}.log','cfg':f'{name}.cfg'}
        results.append(result)
        print(f"{n} objects: {verdict}; states={result['distinct_states']}; deadlock={args.deadlock}",flush=True)
    summary={'source_sha256':hashlib.sha256(tla.read_bytes()).hexdigest(),
             'jar_sha256':hashlib.sha256(jar.read_bytes()).hexdigest(),
             'n_objects_requested':args.objects,'deadlock_check':args.deadlock,'runs':results,
             'all_pass':all(r['verdict']=='PASS' for r in results),
             'scope':'Finite configuration of the abstract TLA+ release workflow; not 60K-object verification'}
    (out/f'tlc_extended_{args.deadlock}.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    if not summary['all_pass']:
        raise SystemExit('Not all TLC configurations passed. Inspect logs; do not report unverified PASS.')

if __name__=='__main__':main()
