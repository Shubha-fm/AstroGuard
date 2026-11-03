#!/usr/bin/env python3
"""Build reviewer inputs from actual AstroGuard 60K 15-epoch ensemble CSVs.

Run from the AstroGuard_18K_macOS_Fresh_Start project root.
No model training, no fabricated thresholds, no file modifications to source outputs.
"""
from pathlib import Path
import argparse
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.stats import binomtest

CLASSES=['Periodic','Stochastic','Transient']
FULL=['rf','bigru','cnn','transformer','classical24a','classical24b']
MATCHED=['quantum24','classical24a','classical24b']

def macrof1(y,p):
    fs=[]
    for cls in CLASSES:
        tp=np.count_nonzero((y==cls)&(p==cls))
        fp=np.count_nonzero((y!=cls)&(p==cls))
        fn=np.count_nonzero((y==cls)&(p!=cls))
        fs.append(2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.0)
    return float(np.mean(fs))

def read_model(root,group,name):
    p=root/group/'analysis'/f'ensemble_{name}_test_128.csv'
    if not p.is_file():
        raise FileNotFoundError(f'Missing {p}. Extract the relevant ensemble CSV from its 15ep ZIP first.')
    df=pd.read_csv(p)
    required={'object_id','broad_class','prediction','split','prefix','trained_n','n_valid',
              'first_mjd_observed','last_mjd_observed','median_mag_err','n_g','n_r','confidence','epistemic_uncertainty'}
    missing=required-set(df.columns)
    if missing:raise ValueError(f'{p}: missing {sorted(missing)}')
    if not (df['split']=='test').all() or not (pd.to_numeric(df['prefix'])==128).all():
        raise ValueError(f'{p}: this script requires 128-prefix held-out rows only')
    if len(df)!=12001 or df.object_id.duplicated().any():
        raise ValueError(f'{p}: expected 12001 unique test objects; got {len(df)}')
    expected_train=3000 if group=='matched' else 39000
    if not (pd.to_numeric(df.trained_n)==expected_train).all():
        raise ValueError(f'{p}: expected trained_n={expected_train}')
    return df.sort_values('object_id').reset_index(drop=True)

def main():
    a=argparse.ArgumentParser()
    a.add_argument('--root',type=Path,default=Path('REVIEWER_60K_INPUTS'))
    a.add_argument('--out',type=Path,default=Path('REVIEWER_60K_FROM_ENSEMBLES'))
    a.add_argument('--bootstrap',type=int,default=3000)
    args=a.parse_args()
    if args.bootstrap<100:raise SystemExit('--bootstrap must be >=100')
    args.out.mkdir(parents=True,exist_ok=True)
    dfs={}
    for group,names in [('classical',FULL),('matched',MATCHED)]:
        for name in names:dfs[group,name]=read_model(args.root,group,name)
    ref=dfs['classical','rf'][['object_id','broad_class']]
    for key,df in dfs.items():
        if not df[['object_id','broad_class']].equals(ref):
            raise ValueError(f'{key}: held-out object IDs or truth disagree with reference')
    n= len(ref)
    ref.broad_class.value_counts().reindex(CLASSES,fill_value=0).rename_axis('broad_class').reset_index(name='heldout_n').to_csv(args.out/'heldout_class_counts.csv',index=False)
    rows=[]; allconf=[]
    for (group,name),df in dfs.items():
        y=df.broad_class.to_numpy(dtype=str);p=df.prediction.to_numpy(dtype=str)
        rows.append({'group':group,'model':name,'train_n':3000 if group=='matched' else 39000,'heldout_n':n,'ensemble_macro_f1':macrof1(y,p),'ensemble_accuracy':float(np.mean(y==p))})
        for yc in CLASSES:
            for pc in CLASSES:
                allconf.append({'group':group,'model':name,'true_class':yc,'pred_class':pc,'count':int(np.count_nonzero((y==yc)&(p==pc)))})
    pd.DataFrame(rows).to_csv(args.out/'all_ensemble_metrics.csv',index=False)
    pd.DataFrame(allconf).to_csv(args.out/'all_ensemble_confusion_counts.csv',index=False)
    # Dataset properties on TEST portion only; these are NOT full 60K histograms.
    rf=dfs['classical','rf']
    properties=pd.DataFrame({'object_id':rf.object_id,'broad_class':rf.broad_class,
        'n_valid':pd.to_numeric(rf.n_valid,errors='coerce'),
        'timespan_days':pd.to_numeric(rf.last_mjd_observed,errors='coerce')-pd.to_numeric(rf.first_mjd_observed,errors='coerce'),
        'original_class':rf.original_class if 'original_class' in rf else ''})
    properties.to_csv(args.out/'heldout_object_properties.csv',index=False)
    for key,label in [('n_valid','Valid detections (retained)'),('timespan_days','Observed MJD span (days)')]:
        values=properties[key].dropna()
        plt.figure(figsize=(7,4));plt.hist(values,bins=40)
        plt.xlabel(label);plt.ylabel('Held-out objects');plt.title('60K study: held-out subset only (n=12,001)')
        plt.tight_layout();plt.savefig(args.out/f'heldout_{key}_histogram.png',dpi=190);plt.close()
    if 'original_class' in properties:
        properties.groupby(['broad_class','original_class']).size().rename('heldout_n').reset_index().to_csv(args.out/'heldout_subclass_counts.csv',index=False)
    # Object-resampling interval for mean ensemble predictions (conditional on fixed ensemble and test cohort).
    q=dfs['matched','quantum24'];y=q.broad_class.to_numpy(dtype=str);qp=q.prediction.to_numpy(dtype=str)
    rng=np.random.default_rng(42)
    results=[]
    for name in ['classical24a','classical24b']:
        c=dfs['matched',name];cp=c.prediction.to_numpy(dtype=str)
        a=(qp==y);b=(cp==y)
        qa=int(np.count_nonzero(a & ~b));ca=int(np.count_nonzero(~a & b))
        diffs=np.empty(args.bootstrap)
        for i in range(args.bootstrap):
            ids=rng.integers(0,n,n)
            diffs[i]=macrof1(y[ids],qp[ids])-macrof1(y[ids],cp[ids])
        results.append({'quantum_model':'quantum24','control_model':name,'n_paired_objects':n,
            'delta_ensemble_macro_f1':macrof1(y,qp)-macrof1(y,cp),
            'bootstrap_95_low':float(np.quantile(diffs,.025)),'bootstrap_95_high':float(np.quantile(diffs,.975)),
            'discordant_quantum_only_correct':qa,'discordant_control_only_correct':ca,
            'exact_mcnemar_p':float(binomtest(min(qa,ca),qa+ca,.5).pvalue) if qa+ca else 1.0})
    pd.DataFrame(results).to_csv(args.out/'matched_ensemble_paired_bootstrap_mcnemar.csv',index=False)
    # Descriptive weight sensitivity: fixed quality-only top-k, NO threshold-based four-condition release gate.
    src=rf
    nvalid=pd.to_numeric(src.n_valid,errors='coerce').to_numpy(float)
    err=pd.to_numeric(src.median_mag_err,errors='coerce').to_numpy(float)
    both=((pd.to_numeric(src.n_g,errors='coerce').to_numpy(float)>0)&(pd.to_numeric(src.n_r,errors='coerce').to_numpy(float)>0)).astype(float)
    conf=pd.to_numeric(src.confidence,errors='coerce').to_numpy(float)
    yy=src.broad_class.to_numpy(dtype=str);pp=src.prediction.to_numpy(dtype=str)
    valid=np.isfinite(nvalid)&np.isfinite(err)&np.isfinite(conf)
    sens=[]
    for weights in [(0.5,0.35,0.15),(0.4,0.45,0.15),(0.6,0.25,0.15),(0.5,0.25,0.25),(0.5,0.45,0.05)]:
        score=weights[0]*np.minimum(nvalid/128,1)+weights[1]*np.exp(-err)+weights[2]*both
        candidates=np.flatnonzero(valid)
        for coverage in [0.25,0.5,0.75,1.0]:
            k=max(1,int(np.floor(len(candidates)*coverage)))
            chosen=candidates[np.argsort(score[candidates],kind='stable')[-k:]]
            sens.append({'w_n':weights[0],'w_error':weights[1],'w_bands':weights[2],
                'nominal_top_quality_fraction':coverage,'n_selected':k,'selected_error':float(np.mean(yy[chosen]!=pp[chosen])),
                'model':'rf_ensemble','method':'descriptive fixed-coverage quality ranking; NOT full release-gate test'})
    pd.DataFrame(sens).to_csv(args.out/'descriptive_quality_weight_sensitivity.csv',index=False)
    (args.out/'ANALYSIS_STATUS.md').write_text('''# Verified scope of 60K ensemble analyses\n\n- Nine ensemble files, each 12,001 distinct test objects, aligned on IDs/truth.\n- Object-level paired bootstrap and exact McNemar compare single five-seed *ensembles*; not independent seed-level tests or equivalence claims.\n- Dataset detection and MJD-span histograms cover only held-out 12,001 objects; full 60K manifest still needed.\n- Quality-weight variation is descriptive top-quality selection on fixed RF predictions. It is NOT validation-selected four-predicate release-gate assessment.\n- No validated tau_C, tau_U, tau_Q or operational S(x) supplied; full release-gate counts cannot be claimed.\n- Measured confusion matrix available for each of 9 ensemble models.\n- Class labels are ALeRCE pseudolabels, not ground-truth science labels.\n''')
    print('Completed 60K ensemble reviewer analysis. Results:',args.out.resolve())
    print('Full release-gate study and full 60K manifest audit remain outstanding.')

if __name__=='__main__': main()
