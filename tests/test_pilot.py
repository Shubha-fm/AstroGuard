"""Synthetic software tests; NOT astronomical evidence."""
from pathlib import Path
import sqlite3
from suite.collect import collect
from run_stratified_pilot import pilot
from tests.test_240k import FakeALeRCE


def test_stratified_checkpoint_resume_no_duplicates(tmp_path):
    root=tmp_path/'input';out=tmp_path/'results'
    fake=FakeALeRCE()
    # Populate all finite class-filtered pages, then prefill only the earliest
    # subclass to mimic 5k initial SNIa attempts.
    collect(root,per_subclass=2,pages=3,page_size=3,query_only=True,delay=0,client=fake)
    db=sqlite3.connect(root/'collection_progress.sqlite3')
    # Add true cross-broad conflict to verify it is never accepted by pilot.
    db.execute("INSERT INTO candidates VALUES ('ZTF_TEST_Conflict','Transient','SNIbc',888,'a','0.5')")
    db.execute("INSERT INTO candidates VALUES ('ZTF_TEST_Conflict','Stochastic','AGN',888,'a','0.5')")
    db.commit();db.close()
    a=pilot(root,per_broad=6,max_new=7,delay=0,output=out,client=fake)
    assert a['new_attempts_this_invocation']==7
    b=pilot(root,per_broad=6,max_new=15,delay=0,output=out,client=fake)
    assert b['complete'] is True
    assert b['completed_pilot_attempts_by_broad']=={'Periodic':6,'Stochastic':6,'Transient':6}
    assert b['accepted_pilot_by_broad']=={'Periodic':6,'Stochastic':6,'Transient':6}
    assert sum(b['total_accepted_including_previous_batches'].values())==18
    assert (out/'SEND_ME_PILOT_REPORT.zip').exists()
    db=sqlite3.connect(root/'collection_progress.sqlite3')
    assert db.execute('SELECT COUNT(*) FROM accepted WHERE oid=?',('ZTF_TEST_Conflict',)).fetchone()[0]==0
    assert db.execute('SELECT COUNT(DISTINCT oid) FROM accepted').fetchone()[0]==18
    db.close()
    c=pilot(root,per_broad=6,max_new=10,delay=0,output=out,client=fake)
    assert c['new_attempts_this_invocation']==0
