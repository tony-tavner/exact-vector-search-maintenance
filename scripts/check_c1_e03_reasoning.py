"""E03 mathematical/fixture audit; no C1 updater, index or fast certificate implementation."""
import argparse
import hashlib
import importlib.util
import itertools
import json
import math
import random
import sys
from copy import deepcopy
from fractions import Fraction as F
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ATTEMPT='E03_2026-11-18_02'
U=F(1,2**53)
ETA=F(1,2**1074)


def canonical(q,x):return math.fsum(a*b for a,b in zip(q,x))


def real_dot(q,x):return sum((F(a)*F(b) for a,b in zip(q,x)),F(0))


def real_box(box,z,w):
    return sum((max(F(lo)*(F(a)-F(b)),F(hi)*(F(a)-F(b)))
                for (lo,hi),a,b in zip(box,z,w)),F(0))


def error_given_F(box,x):
    ax=sum((max(abs(F(lo)),abs(F(hi)))*abs(F(a)) for (lo,hi),a in zip(box,x)),F(0))
    return (5*U+4*U*U)*ax+(1+4*U)*len(x)*ETA/2+4*ETA


def conditional_bound(box,z,w):
    # This is NOT an enabled runtime certificate. F is unproved for canonical backend.
    return real_box(box,z,w)+error_given_F(box,z)+error_given_F(box,w)


def numeric_checks():
    results=[]
    q=[.6,.8];w=[.6,.8];z=[math.nextafter(.6,math.inf),math.nextafter(.8,-math.inf)]
    for name,qi,zi,wi in [
        ('rounded_products_tie',q,z,w),
        ('subnormal_product_tie',[1.0,float(ETA)],[1.0,0.0],[1.0,float(ETA)])]:
        real=real_dot(qi,zi)-real_dot(qi,wi)
        diff=F(canonical(qi,zi))-F(canonical(qi,wi))
        box=list(zip(qi,qi));cond=conditional_bound(box,zi,wi)
        assert real<0 and diff==0 and cond>=0
        results.append({'case':name,'q':qi,'z':zi,'w':wi,'real_difference':str(real),
                        'canonical_difference':str(diff),'conditional_bound':str(cond),
                        'unsafe_real_accepts':True,'scan_accepts':False,
                        'conditional_formula_rejects_in_this_example':True})

    grid=[-1.0,0.0,1.0];intervals=[(lo,hi) for lo in grid for hi in grid if lo<=hi]
    count=0
    for box in itertools.product(intervals,repeat=2):
        for z in itertools.product(grid,repeat=2):
            for w in itertools.product(grid,repeat=2):
                bound=real_box(box,z,w)
                corners=list(itertools.product(*[tuple(sorted(set(t))) for t in box]))
                actual=max(real_dot(q,z)-real_dot(q,w) for q in corners)
                assert bound==actual
                assert all(F(canonical(q,z))-F(canonical(q,w))<=conditional_bound(box,z,w) for q in corners)
                count+=1
    rng=random.Random(2026111802)
    values=[0.0,float(ETA),-float(ETA),math.ldexp(1.,-1022),math.ldexp(-1.,-1022),
            math.ldexp(1.,-500),math.ldexp(-1.,-500),math.ldexp(1.,-53),.6,-.6,.8,-.8,1.,-1.]
    observations=[]
    for i in range(240):
        dim=[1,2,3,7,32,768][i%6]
        q=[rng.choice(values) for _ in range(dim)]
        z=[rng.choice(values) for _ in range(dim)];w=[rng.choice(values) for _ in range(dim)]
        box=list(zip(q,q));b=conditional_bound(box,z,w)
        diff=F(canonical(q,z))-F(canonical(q,w));assert diff<=b
        for x in [z,w]:
            products=[a*b for a,b in zip(q,x)]
            exact=sum((F(v) for v in products),F(0))
            error=abs(F(math.fsum(products))-exact)
            model=4*U*sum((abs(F(v)) for v in products),F(0))+4*ETA
            assert error<=model
        observations.append({'case':i,'dimension':dim,'conditional_bound_contains_actual':True,
                             'observed_F_for_two_lists':True})
    return {'counterexamples':results,'box_linear_identity_cases':count,
            'finite_stress_pairs':len(observations),'finite_fsum_lists':2*len(observations),
            'observations':observations,'hypothesis_F_proved':False,
            'fast_backend_enabled':False,'scope':'Exact-rational box identity plus finite observations of conditional formula and F. These observations are NOT a uniform fsum proof.'}


def rank(state,d):return (-state[d][0],d)


def finite_relation():
    # Full derived-row state includes version. A true certificate requires exact row equality.
    states=[None,(-1,'v1'),(0,'v1'),(1,'v1'),(0,'v2')]
    opts=[]
    for old in states:
        for new in states:
            if old==new:opts.extend([(old,new,False,False),(old,new,True,False),(old,new,True,True)])
            else:opts.append((old,new,True,False))
    assert len(opts)==35
    transitions=configurations=prefixes=sufficient=fallback=0
    for change in itertools.product(opts,repeat=3):
        transitions+=1
        old={d:a for d,(a,b,t,cert) in zip('ABC',change) if a is not None}
        new={d:b for d,(a,b,t,cert) in zip('ABC',change) if b is not None}
        dq={d for d,(a,b,t,cert) in zip('ABC',change) if t and not cert}
        for d in set(old)|set(new):
            if d not in dq:assert old.get(d)==new.get(d)
        before=sorted(old,key=lambda d:rank(old,d));after=sorted(new,key=lambda d:rank(new,d))
        for k in range(1,4):
            for cap in range(k,4):
                configurations+=1
                for ell in range(min(k,len(before)),min(cap,len(before))+1):
                    prefixes+=1;reserve=before[:ell]
                    boundary=rank(old,reserve[-1]) if reserve else None
                    candidates=[(d,old[d]) for d in reserve if d not in dq]
                    candidates += [(d,new[d]) for d in dq if d in new and (boundary is None or rank(new,d)<=boundary)]
                    candidates.sort(key=lambda rec:(-rec[1][0],rec[0]))
                    theoretical=[(d,new[d]) for d in after if boundary is None or rank(new,d)<=boundary]
                    assert candidates==theoretical
                    if len(candidates)>=k:
                        sufficient+=1;retained=candidates[:cap]
                        assert retained==[(d,new[d]) for d in after[:len(retained)]]
                        assert retained[:k]==[(d,new[d]) for d in after[:k]]
                    else:fallback+=1
    return {'passed':True,'labelled_transitions':transitions,'k_cap_configurations':configurations,
            'valid_prefix_instances':prefixes,'sufficient':sufficient,'requires_full_search':fallback,
            'scope':'Finite derived-row lemma with 3 docs, ties, absence, versions and all sound certify/unknown flags. It tests the reduced D_q identity, not construction of certificates or a production engine.'}


def fixtures_and_oracle():
    src=ROOT/'reports/e_stages/E02/E02_2026-11-18_01/candidate_checks_v2.json'
    cases=deepcopy(json.loads(src.read_text())['manual_cases'])
    for case in cases:case['origin']='R02/E02 hand case; original preserved'
    query={'query_id':'q','query_version':'qv1','config_version':'C1-v02-toy',
           'query_time':'2026-11-18','filter':{},'k':1,'vector':[1.,0.]}
    def frag(fid,vec,version='v1'):return {'fragment_id':fid,'text_version':version,'vector':vec}
    def doc(fs,did='D'):return {'doc_id':did,'fragments':fs,'metadata':{'enabled':True,'valid_from':'2026-01-01','valid_to':'2027-01-01'}}
    def hit(d,f,v='v1'):return [[d,f,v]]
    def add(cid,before,after,eb,ea,reason,vec=None):
        q=deepcopy(query)
        if vec is not None:q['vector']=vec
        cases.append({'id':cid,'query':q,'before':before,'after':after,'expected_before':eb,
                      'expected_after':ea,'reason':reason,'origin':'E03 C1 v0.2 hand case'})
    w=[.6,.8];z=[math.nextafter(.6,math.inf),math.nextafter(.8,-math.inf)]
    add('canonical_tie_defeats_real_bound',[doc([frag('z',w)])],
        [doc([frag('z',w),frag('a',z)])],hit('D','z'),hit('D','a'),
        'Real dot difference negative, canonical scores tie at 1.0; new UTF8 ID wins.',[.6,.8])
    tiny=float(ETA)
    add('subnormal_tie_defeats_real_bound',[doc([frag('z',[1.,tiny])])],
        [doc([frag('z',[1.,tiny]),frag('a',[1.,0.])])],hit('D','z'),hit('D','a'),
        'Product eta^2 underflows; mathematical strict order becomes canonical tie.',[1.,tiny])
    old=doc([frag('w',[1.,0.]),frag('r',[.8,.6])])
    new=doc([frag('w',[1.,0.]),frag('r',[.8,-.6],'v2')])
    add('cell_only_q1', [old],[new],hit('D','w'),hit('D','w'),
        'Block q1 may certify D; certificate cannot remove D globally.',[1.,0.])
    add('cell_only_q2', [old],[new],hit('D','r'),hit('D','w'),
        'Same document event affects q2; global deletion from D would retain wrong old winner.',[0.,1.])
    add('certified_doc_other_new_leader',[old],[new,doc([frag('f',[1.,0.])],'A')],
        hit('D','w'),hit('A','f'),'D is unchanged for q, but another new document wins by doc ID; cannot reuse whole query answer.')
    add('negative_strict_domination',[doc([frag('w',[-.6,.8])])],
        [doc([frag('w',[-.6,.8]),frag('a',[-.8,.6])])],hit('D','w'),hit('D','w'),
        'All scores negative; strict canonical difference is still a valid relation.')
    dest=ROOT/'tests/fixtures/method_cases/C1_v02';dest.mkdir(parents=True,exist_ok=True)
    path=dest/'cases.json'
    encoded=json.dumps({'version':'A-E03-C1-0.2-audit','cases':cases,
        'scope':'Hand full-snapshot answers; not execution of C1 certificates, transactions or index.'},ensure_ascii=False,indent=2)+'\n'
    if path.exists():
        assert path.read_text()==encoded, 'Existing fixture differs: use a new version; never overwrite'
    else:
        path.write_text(encoded)
    spec=importlib.util.spec_from_file_location('oracle',ROOT/'tests/verify_e01_fixtures.py')
    oracle=importlib.util.module_from_spec(spec);spec.loader.exec_module(oracle)
    out=[]
    for c in cases:
        for side in ['before','after']:
            answer=oracle.exact(c[side],c['query'],c['id']+':'+side)
            assert answer['ordered_hits']==c['expected_'+side],(c['id'],side,answer)
            out.append({'case':c['id'],'snapshot':side,'answer':answer,'passed':True})
    return {'passed':True,'case_count':len(cases),'snapshot_count':len(out),'results':out,
            'fixture_path':str(path.relative_to(ROOT)),'fixture_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True);args=ap.parse_args()
    output=Path(args.output);assert not output.exists()
    numeric=numeric_checks();finite=finite_relation();fixtures=fixtures_and_oracle()
    report={'article_id':'A','attempt_id':ATTEMPT,'method_version':'A-E03-C1-0.2-audit','all_checks_passed':True,
      'numeric':numeric,'finite_relation':finite,'fixtures':fixtures,'python':sys.version,
      'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
      'method_implemented':False,'performance_experiments_executed':False,'E04_started':False,
      'fast_canonical_bound_proved':False,'scope':'Reasoning/finite counterexamples only; passing checks does not close F or establish novelty/speed.'}
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'all_checks_passed':True,'numeric_box_cases':numeric['box_linear_identity_cases'],
       'numeric_stress_pairs':numeric['finite_stress_pairs'],'fixtures':fixtures['case_count'],
       'snapshots':fixtures['snapshot_count'],'finite_relation':finite,
       'fast_canonical_bound_proved':False}))


if __name__=='__main__':main()
