"""Differential/property acceptance suite. New run paths only; no E05 benchmark."""
from pathlib import Path
import argparse,copy,hashlib,importlib.util,json,math,random,struct,subprocess,sys,time,traceback
import numpy as np
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'src'))
from pvldb_a.engine import Engine,METHODS
from pvldb_a.oracle import exact
from pvldb_a.numeric import NumericContext,bounds,native
from pvldb_a import persistent as avl
from pvldb_a.reserve import Adaptive
COUNTS={};DETAIL=[]
def add(k,n=1):COUNTS[k]=COUNTS.get(k,0)+n
def check_engine(e,docs,queries,version):
    actual=e.answers()
    expected={q['query_id']:exact(docs,q,version) for q in queries}
    assert actual==expected,(e.method,version,actual,expected)
    e.check_invariants();add('differential_snapshots');add('query_outputs',len(queries))
    # Prefix sufficiency and complete records checked independently using a larger k.
    for q in queries:
        full=copy.deepcopy(q);full['k']=max(1,len(docs));allhits=exact(docs,full,version)['ordered_hits']
        rs=e._root.reserves[q['query_id']]
        assert [r.hit for r in rs]==allhits[:len(rs)]
        assert len(rs)>=min(q['k'],len(allhits))
        add('reserve_prefix_checks')

def fixtures():
    spec=importlib.util.spec_from_file_location('e01_oracle',R/'tests/verify_e01_fixtures.py');o=importlib.util.module_from_spec(spec);spec.loader.exec_module(o)
    for fn in ['tests/fixtures/e01_contract_v1.json','tests/fixtures/method_cases/C1_v02/cases.json']:
        data=json.loads((R/fn).read_text())
        for c in data['cases']:
            before=c['before']['documents'] if isinstance(c['before'],dict) else c['before']
            after=c['after']['documents'] if isinstance(c['after'],dict) else c['after'];q=c['query']
            for side,ds in [('before',before),('after',after)]:
                assert exact(ds,q,side)['ordered_hits']==c['expected_'+side]
                assert exact(ds,q,side)==o.exact(ds,q,side);add('hand_oracle_snapshots')
            for method in METHODS:
                e=Engine(method,leaf_limit=2);e.build(before,[q],'c0');check_engine(e,before,[q],'c0')
                amap={d['doc_id']:d for d in after};events=[{'op':'delete_document','doc_id':d['doc_id']} for d in before if d['doc_id'] not in amap]
                events += [{'op':'put_document','document':d} for d in after]
                e.apply(events,'c1','c0');check_engine(e,after,[q],'c1');add('fixture_method_cases')
                if c['id']=='two_sided_nonwinning_replace':DETAIL.append({'case':c['id'],'method':method,'counts':e.last_metrics['counts']})
        for c in data.get('invalid_cases',[]):
            for method in METHODS:
                try:Engine(method).build(c['documents'],[c['query']],'invalid')
                except (ValueError,OverflowError):add('rejected_invalid_builds')
                else:raise AssertionError((method,'invalid accepted',c['id']))

def unitvec(rng,p=3):
    v=[rng.uniform(-1,1) for _ in range(p)];n=math.sqrt(math.fsum(x*x for x in v));return [x/n for x in v]
def meta():return {'enabled':True,'role':'critical-maintenance','valid_from':'2026-01-01','valid_to':'2027-01-01'}
def make_doc(i,v,version='v0'):
    return {'doc_id':'D'+str(i),'metadata':meta(),'fragments':[{'fragment_id':'f'+str(i),'text_version':version,'text':'synthetic personnel competency fixture '+str(i),'vector':v}]}
def make_q(i,v,k=2):
    return {'query_id':'Q'+str(i),'query_version':'q0','config_version':'e04-synthetic-v1','vector':v,'k':k,'query_time':'2026-11-18','filter':{'role':'critical-maintenance'}}

def random_histories():
    for seed in range(12):
        rng=random.Random(180400+seed);docs=[make_doc(i,unitvec(rng)) for i in range(6)]
        qs=[make_q(i,unitvec(rng),1+i%3) for i in range(4)]
        engines=[Engine(method,leaf_limit=3,certificate_budget=3) for method in METHODS]
        for e in engines:e.build(copy.deepcopy(docs),copy.deepcopy(qs),'r0');check_engine(e,docs,qs,'r0')
        corpus={d['doc_id']:d for d in copy.deepcopy(docs)}
        for step in range(1,25):
            did='D'+str(rng.randrange(9));op=step%6;events=[]
            if did not in corpus:
                d=make_doc(did[1:],unitvec(rng),'r'+str(step));corpus[did]=d;events=[{'op':'put_document','document':copy.deepcopy(d)}]
            elif op==0:
                del corpus[did];events=[{'op':'delete_document','doc_id':did}]
            elif op==1:
                corpus[did]['metadata']['enabled']=not corpus[did]['metadata']['enabled']
                events=[{'op':'metadata','doc_id':did,'changes':{'enabled':corpus[did]['metadata']['enabled']}}]
            elif op==2:
                fs=corpus[did]['fragments'];fid=fs[0]['fragment_id'] if fs else 'new'+did
                f={'fragment_id':fid,'text_version':'r'+str(step),'vector':unitvec(rng),'text':'changed synthetic requirement '+str(step)}
                corpus[did]['fragments']=[f]+[x for x in fs if x['fragment_id']!=fid]
                events=[{'op':'put_fragment','doc_id':did,'fragment':copy.deepcopy(f)}]
            elif op==3:
                f={'fragment_id':'extra'+str(step),'text_version':'r'+str(step),'vector':unitvec(rng),'text':'extra requirement'}
                corpus[did]['fragments'].append(f);events=[{'op':'put_fragment','doc_id':did,'fragment':copy.deepcopy(f)}]
            elif op==4 and corpus[did]['fragments']:
                fid=corpus[did]['fragments'].pop(0)['fragment_id'];events=[{'op':'delete_fragment','doc_id':did,'fragment_id':fid}]
            else:
                # Net-same ordered metadata pair; final snapshot still publishes a version.
                current=corpus[did]['metadata']['enabled'];events=[{'op':'metadata','doc_id':did,'changes':{'enabled':not current}},{'op':'metadata','doc_id':did,'changes':{'enabled':current}}]
            ds=list(corpus.values())
            for e in engines:e.apply(copy.deepcopy(events),'r'+str(step),'r'+str(step-1));check_engine(e,ds,qs,'r'+str(step))
        add('random_histories');add('atomic_random_batches',24*len(engines))

def atomic_and_registry():
    docs=[make_doc(0,[1.,0.]),make_doc(1,[0.,1.]),make_doc(2,[-1.,0.])];qs=[make_q(0,[1.,0.],1)]
    class CallbackFloat:
        def __float__(self):raise AssertionError('untrusted numeric callback executed')
    for source in ('vector','metadata'):
        bad=copy.deepcopy(docs)
        if source=='vector':bad[0]['fragments'][0]['vector'][0]=CallbackFloat()
        else:bad[0]['metadata']['role']=CallbackFloat()
        try:Engine('C1').build(bad,qs,'callback')
        except ValueError:add('callback_input_rejections')
        else:raise AssertionError('callback input accepted')
    for method in METHODS:
        e=Engine(method,leaf_limit=1,hybrid_fraction=1);e.build(docs,qs,'a0');saved=e.answers();root=e._root
        bad=copy.deepcopy(docs[0]);bad['fragments'][0]['vector']=[0.,1.]
        invalid=[([{'op':'put_document','document':bad}],{}),([],{'cap':0}),([],{'queries':[dict(qs[0],vector=[0.,1.])]}),
                 ([{'op':'metadata','doc_id':'D0','changes':{'valid_from':'not-date'}}],{}),([],{'fault_at':'before_publish'}),
                 ([],{'fault_at':'after_validation'})]
        for events,kw in invalid:
            try:e.apply(events,'bad','a0',**kw)
            except (ValueError,RuntimeError):pass
            else:raise AssertionError(('did not reject',method,events,kw))
            assert e._root is root and e.answers()==saved;add('atomic_failure_rollbacks')
        with e.pin() as reader:
            e.apply([{'op':'metadata','doc_id':'D0','changes':{'enabled':False}}],'a1','a0')
            assert reader.answers()==saved
            try:e.apply([],'a2','a1')
            except RuntimeError as ex:assert str(ex)=='reader_backpressure';add('reader_backpressure_checks')
            else:raise AssertionError('unbounded retained roots')
        try:reader.answers()
        except RuntimeError:add('released_reader_checks')
        else:raise AssertionError('released reader usable')
        changed=copy.deepcopy(docs);changed[0]['metadata']['enabled']=False;check_engine(e,changed,qs,'a1')
        qnew=dict(qs[0],query_version='q1',vector=[0.,1.],k=2)
        e.apply([],'a2','a1',queries=[qnew]);check_engine(e,changed,[qnew],'a2')
        e.apply([],'a3','a2',queries=[]);check_engine(e,changed,[],'a3')
        e.apply([],'a4','a3',queries=[qnew],cap=5);check_engine(e,changed,[qnew],'a4')
        qcfg=dict(qnew,config_version='e04-new-model',vector=[1.,0.,0.],query_version='q2')
        rebuilt=copy.deepcopy(changed)
        for d in rebuilt:
            for f in d['fragments']:f['vector']=f['vector']+[0.]
        e.apply([],'a5','a4',queries=[qcfg],documents=rebuilt);check_engine(e,rebuilt,[qcfg],'a5')
        # IDs/version aliases across deletion/reinsertion must still be rejected.
        e.apply([{'op':'delete_document','doc_id':'D0'}],'a6','a5');before=e.answers()
        bad=copy.deepcopy(rebuilt[0]);bad['fragments'][0]['vector']=[0.,1.,0.]
        try:e.apply([{'op':'put_document','document':bad}],'a7','a6')
        except ValueError:assert e.answers()==before;add('historical_alias_rejections')
        else:raise AssertionError('deleted identity alias accepted')
        # An invalid intermediate event cannot be hidden by a net-same final snapshot.
        bad=copy.deepcopy(rebuilt[1]);bad['fragments'][0]['vector']=[1.,0.,0.]
        try:e.apply([{'op':'put_document','document':bad},{'op':'put_document','document':rebuilt[1]}],'a7','a6')
        except ValueError:assert e.answers()==before;add('intermediate_alias_rejections')
        else:raise AssertionError('intermediate alias accepted')

def reversibility_and_pruning():
    # Positive C1 example with complete source-byte identities. Missing bytes
    # must instead produce UNKNOWN even when old toy outputs happen to agree.
    c=json.loads((R/'tests/fixtures/method_cases/C1_v02/cases.json').read_text())['cases'][0]
    for supplied in (False,True):
        before=copy.deepcopy(c['before']);after=copy.deepcopy(c['after'])
        if supplied:
            for ds in (before,after):
                for d in ds:
                    for f in d['fragments']:f['text']='Explicit synthetic source '+f['fragment_id']+' '+f['text_version']
        for method in ('C1','C1_FLAT','C1_SEPARATE','C1_MARGIN'):
            e=Engine(method);e.build(before,[c['query']],'id0')
            e.apply([{'op':'put_document','document':d} for d in after],'id1','id0')
            assert e.last_metrics['counts'].get('certified_cells',0)==int(supplied)
            if supplied and method in ('C1','C1_SEPARATE'):assert e.last_metrics['counts'].get('score_pairs',0)==0
            if supplied and method=='C1_FLAT':assert e.last_metrics['counts'].get('postings_visited',0)>0
            check_engine(e,after,[c['query']],'id1');add('complete_source_identity_checks')
    docs=[make_doc(i,[x,math.sqrt(1-x*x)]) for i,x in enumerate([1.,.9,.8,.7,.6])]
    qs=[make_q(i,[1.,0.],1) for i in range(5)]
    for method in METHODS:
        e=Engine(method,leaf_limit=2);e.build(docs,qs,'p0');initial=e.answers()
        low=make_doc(8,[0.,1.])
        e.apply([{'op':'put_document','document':low}],'p1','p0');check_engine(e,docs+[low],qs,'p1')
        if method in ('B4_SIMPFER_EXACT','B5_SIMPFERPP_EXACT'):
            assert e.last_metrics['counts'].get('reverse_blocks_pruned',0)==3;add('specialized_pruning_checks')
        e.apply([{'op':'delete_document','doc_id':'D8'}],'p2','p1')
        assert {i:x['ordered_hits'] for i,x in e.answers().items()}=={i:x['ordered_hits'] for i,x in initial.items()};add('reversible_history_checks')
        x=Engine(method);y=Engine(method);x.build(docs,qs,'c0');y.build(docs,qs,'c0')
        changes=[{'op':'metadata','doc_id':'D0','changes':{'enabled':False}},{'op':'metadata','doc_id':'D1','changes':{'enabled':False}}]
        a=x.apply(changes,'c1','c0');b=y.apply(list(reversed(changes)),'c1','c0');assert a==b;add('commuting_batch_checks')
    # Guard fallback and budget exhaustion must preserve the full output.
    for budget,disabled in [(0,False),(1,False),(10,True)]:
        e=Engine('C1',certificate_budget=budget,disable_box=disabled,leaf_limit=2);e.build(docs,qs,'g0')
        new=copy.deepcopy(docs[0]);new['fragments'].append({'fragment_id':'z','text_version':'v1','vector':[0.,1.]})
        e.apply([{'op':'put_document','document':new}],'g1','g0');check_engine(e,[new]+docs[1:],qs,'g1');add('guard_or_budget_fallback_cases')

def numeric_and_structures():
    ctx=NumericContext();rng=random.Random(1804);pairs=0
    with ctx.region():
        for p in [1,2,3,7,8,17,64,129,768]:
            qs=[[rng.uniform(-1,1) for _ in range(p)] for _ in range(5)]
            xs=[[rng.uniform(-1,1) for _ in range(p)] for _ in range(7)]
            if p>=3:xs[0][:3]=[2**-1074,-2**-1074,2**-1022]
            scores=ctx.matrix(qs,xs,{})
            for i,q in enumerate(qs):
                for j,x in enumerate(xs):
                    expected=math.fsum(a*b for a,b in zip(q,x))
                    assert struct.pack('d',float(scores[i,j]))==struct.pack('d',expected);pairs+=1
        for p in [2,3,768]:
            q=[1.,0.]+[0.]*(p-2);z=[0.,1.]+[0.]*(p-2);w=q
            assert bounds(tuple(zip(q,q)),z,w,ctx,{})<0;add('production_bound_checks')
        for q,z,w in [([.6,.8],[math.nextafter(.6,math.inf),math.nextafter(.8,-math.inf)],[.6,.8]),
                      ([1.,2**-1074],[1.,0.],[1.,2**-1074])]:
            assert bounds(tuple(zip(q,q)),z,w,ctx,{})>=0
            scores=ctx.matrix([q],[z,w],{});assert scores[0,0]==scores[0,1];add('production_tie_counterexamples')
        # E03's exact-rational checker is used only as a second formula evaluation.
        spec=importlib.util.spec_from_file_location('e03_bound',R/'scripts/check_c1_fsum_certificate.py')
        e03=importlib.util.module_from_spec(spec);spec.loader.exec_module(e03)
        for p in [2,3,16,768]:
            for _ in range(8):
                qs=[unitvec(rng,p) for j in range(4)];z=unitvec(rng,p);w=unitvec(rng,p)
                box=tuple((min(t),max(t)) for t in zip(*qs));U=bounds(box,z,w,ctx,{})
                assert U==e03.numeric_bound(box,z,w)
                s=ctx.matrix(qs,[z,w],{})
                from fractions import Fraction
                assert all(Fraction(float(row[0]))-Fraction(float(row[1]))<=U for row in s)
                add('production_bound_formula_cases');add('production_bound_score_pairs',4)
        for sign in (1.,-1.):
            q=[1.,1.,1.];x=[sign*2**-107,sign*2**-53,sign]
            s=float(ctx.matrix([q],[x],{})[0,0]);assert s==math.fsum(x)
            assert abs(s)>1.;add('native_final_correction_cases')
    add('native_bitwise_pairs',pairs)
    # Unsupported rounding environment tested and restored in isolated subprocess.
    code="""import ctypes,sys;sys.path.insert(0,'src');from pvldb_a.numeric import NumericContext,native
c=NumericContext();lib=ctypes.CDLL(None);assert lib.fesetround(0x00400000)==0
try:
 try:
  with c.region():pass
 except RuntimeError:print('guard_rejected')
 else:raise AssertionError('wrong FPCR accepted')
finally:assert lib.fesetround(0)==0
"""
    cp=subprocess.run([sys.executable,'-c',code],cwd=R,capture_output=True,text=True);assert cp.returncode==0 and 'guard_rejected' in cp.stdout;add('non_RN_guard_subprocess')
    root=None;reference={};saved=[]
    for i in range(700):
        key=rng.randrange(120)
        if rng.random()<.65:reference[key]=i;root=avl.put(root,key,i)
        else:reference.pop(key,None);root=avl.delete(root,key)
        assert dict(avl.items(root))==reference
        def balanced(n):
            if n:assert abs(avl.height(n.left)-avl.height(n.right))<=1;balanced(n.left);balanced(n.right)
        balanced(root);saved.append((root,dict(reference)));add('persistent_avl_operations')
    assert all(dict(avl.items(n))==d for n,d in saved);add('persistent_old_roots_verified',len(saved))
    policy=Adaptive(10,10,refill_ns=100000).observe(3,2,1,100)
    assert policy.before_refill(3,100).cap==15
    small=Adaptive(10,8,T=1000,refill_ns=100,update_ns=10).shrink(3);assert small.cap==8
    add('adaptive_policy_endpoint_checks',2)

def development_slice():
    base=R/'data/processed/onet29_3_v1';index=[json.loads(x) for x in (base/'embeddings_development/index.jsonl').read_text().splitlines()]
    vectors=np.load(base/'embeddings_development/vectors.npy',mmap_mode='r',allow_pickle=False)
    positions={(r['kind'],r['id']):r['row'] for r in index}
    docs=[json.loads(s) for s in (base/'documents.jsonl').read_text().splitlines() if json.loads(s)['split']=='development'][:12]
    qs=[json.loads(s) for s in (base/'queries.jsonl').read_text().splitlines() if json.loads(s)['split']=='development'][:4]
    for d in docs:
        for f in d['fragments']:f['vector']=vectors[positions['fragment',f['fragment_id']]].tolist()
    for q in qs:q['vector']=vectors[positions['query',q['query_id']]].tolist()
    after=copy.deepcopy(docs);after[0]['metadata']['enabled']=False
    after[1]['fragments'][0]['text_version']='E04-version-only'
    after[2]['fragments']=after[2]['fragments'][1:]
    events=[{'op':'put_document','document':d} for d in after[:3]]
    for method in METHODS:
        e=Engine(method,leaf_limit=3);e.build(docs,qs,'dev0');check_engine(e,docs,qs,'dev0')
        e.apply(events,'dev1','dev0');check_engine(e,after,qs,'dev1');add('development_method_cases')
    DETAIL.append({'development_slice':{'documents':12,'queries':4,'dimension':768,'split':'development','purpose':'correctness only; no timing comparison or E05 execution'}})

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True);args=ap.parse_args();out=Path(args.output);assert not out.exists();out.parent.mkdir(parents=True,exist_ok=True)
    report={'run_id':out.stem,'implementation_version':'A-E04-0.1','methods':list(METHODS),'E05_started':False,'scope':'E04 differential correctness and infrastructure acceptance, not performance comparison.'}
    phases=[numeric_and_structures,fixtures,random_histories,atomic_and_registry,reversibility_and_pruning,development_slice]
    try:
        for phase in phases:phase();print(phase.__name__,'pass',flush=True)
        report['all_checks_passed']=True
    except BaseException:
        report['all_checks_passed']=False;report['failure']=traceback.format_exc();print(report['failure'],flush=True)
    report['counts']=COUNTS;report['details']=DETAIL
    report['source_hashes']={str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (R/'src/pvldb_a').glob('*') if p.is_file()}
    report['test_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'passed':report['all_checks_passed'],'counts':COUNTS}))
    if not report['all_checks_passed']:raise SystemExit(1)
if __name__=='__main__':main()
