"""Small synthetic software checks; never astronomical evidence."""
from pathlib import Path
import pandas as pd
import numpy as np
from suite.collect import collect,GROUPS
from suite.preprocess import CurveStore, prepare, load_curve, encode_prefix
from suite.analyze_large import bootstrap_27
from tests.make_synthetic_fixture import build

class FakeALeRCE:
    def query_objects(self,**kw):
        sub=kw['class_name'];page=kw['page'];page_size=kw['page_size']
        items=[{'oid':f'ZTF_TEST_{sub.replace(" ","_")}_{i:04d}','probability':0.7} for i in range(5)]
        return pd.DataFrame(items[(page-1)*page_size:page*page_size])
    def query_detections(self,**kw):
        return pd.DataFrame({'mjd':np.arange(22)+60000,'magpsf':np.arange(22)*.01+17,
                             'sigmapsf':np.ones(22)*.12,'fid':np.tile([1,2],11)})

def test_resumable_collection_and_no_duplicate(tmp_path):
    client=FakeALeRCE()
    a=collect(tmp_path/'input',per_subclass=2,pages=3,page_size=3,delay=0.,max_queries=5,client=client)
    assert a['status']=='PAUSED_QUERY'
    assert (tmp_path/'input'/'collection_progress.sqlite3').exists()
    b=collect(tmp_path/'input',per_subclass=2,pages=3,page_size=3,delay=0.,max_downloads=8,client=client)
    assert b['status']=='PAUSED_DOWNLOAD' and b['actual_eligible']==8
    c=collect(tmp_path/'input',per_subclass=2,pages=3,page_size=3,delay=0.,client=client)
    assert c['status']=='TARGET_REACHED' and c['actual_eligible']==24
    manifest=pd.read_csv(tmp_path/'input'/'objects.csv')
    assert len(manifest)==24 and not manifest.object_id.duplicated().any()
    assert sorted(manifest.broad_class.value_counts().tolist())==[8,8,8]

def test_prefix_cache_and_disk_sequence(tmp_path):
    build(tmp_path/'raw',n_each=9)
    r=prepare(tmp_path/'raw/objects.csv',tmp_path/'prepared')
    assert r['n_valid']==27
    ds=CurveStore(tmp_path/'prepared')
    assert isinstance(ds.x,np.memmap)
    ids=ds.indices('test')
    for p in (2,5,10,20,40,80,128):
        x,length,y=ds.batch(ids,prefix=p)
        assert x.shape==(len(ids),128,6)
        original=load_curve(ds.df.iloc[ids[0]].photometry_file)
        arr,ln=encode_prefix(original,p)
        assert np.allclose(x[0],arr)
        assert int(length[0])==ln
        features=ds.features(ids,prefix=p)
        assert features.shape==(len(ids),11)
    assert prepare(tmp_path/'raw/objects.csv',tmp_path/'prepared')['n_valid']==27

def test_joint_bootstrap_equivalent_structure():
    y=np.array([0,1,2]*10);a=y.copy();b=np.roll(y,1)
    lo,median,hi=bootstrap_27(y,a,b,n_boot=200,seed=42)
    assert lo==median==hi==1.0
