#!/usr/bin/env python3
"""E03 proof/counterexample checker only; no updater, index, experiment or E04 engine."""
import argparse, ctypes, hashlib, importlib.util, inspect, itertools, json, math, random, struct, sys
from fractions import Fraction as F
from functools import lru_cache
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'reports/e_stages/E03/E03_2026-11-18_03'
u=F(1,2**53); eta=F(1,2**1074); h=eta/2

def masses(p,A):
    L=p*(p-1)//2
    H=(A+3*L*eta)/(1-4*L*u)
    G=(H+p*h)/(1-p*u)
    return L,H,G

def fsum_error(p,A):
    L,H,G=masses(p,A)
    return L*(2*u*H+2*eta)+(p+8)*u*G+3*p*u*H+(4*p+8)*eta

def score_error(p,A):
    return u*A+p*h+fsum_error(p,(1+u)*A+p*h)

@lru_cache(None)
def coefficients(p):
    beta=score_error(p,F(0));alpha=score_error(p,F(1))-beta
    return alpha,beta

def numeric_bound(box,z,w,context_ok=True,counter=None):
    # The context is independently audited by main. This is a mathematical checker,
    # NOT a production API accepting an untrusted Boolean as runtime attestation.
    p=len(box)
    if not context_ok or not 1<=p<=2**20 or len(z)!=p or len(w)!=p:return None
    S=F(0);Az=F(0);Aw=F(0)
    for (lo,hi),a,b in zip(box,z,w):
        if any(type(x) is not float or not math.isfinite(x) or abs(x)>2 for x in [lo,hi,a,b]):return None
        if lo>hi:return None
        lo,hi,a,b=map(F,[lo,hi,a,b]);d=a-b;v=max(abs(lo),abs(hi))
        S+=max(lo*d,hi*d);Az+=v*abs(a);Aw+=v*abs(b)
        if counter is not None:counter['coordinates']+=1
    alpha,beta=coefficients(p)
    return S+alpha*Az+alpha*Aw+2*beta

def canonical(q,x):return math.fsum(a*b for a,b in zip(q,x))
def exact_dot(q,x):return sum((F(a)*F(b) for a,b in zip(q,x)),F(0))
def pack(v):return struct.pack('>d',v).hex()
def box_of(qs):return [(min(v),max(v)) for v in zip(*qs)]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def traced_fsum(ts):
    # Transcription of the observed finite-input path, for supplemental checks.
    p=len(ts);A=sum(map(lambda x:abs(F(x)),ts),F(0));L,H,G=masses(p,A)
    partials=[];triples=0
    for j,x in enumerate(ts):
        low=[]
        for y in partials:
            if abs(x)<abs(y):x,y=y,x
            T=abs(F(x))+abs(F(y)); hi=x+y;yr=hi-x;lo=y-yr
            assert abs(F(hi)+F(lo)-F(x)-F(y))<=2*u*T+2*eta
            assert abs(F(lo))<=3*u*T+3*eta
            assert abs(F(hi))+abs(F(lo))<=(1+4*u)*T+3*eta
            if lo:low.append(lo)
            x=hi;triples+=1
        if x:low.append(x)
        partials=low
        assert len(partials)<=j+1
        assert sum((abs(F(v)) for v in partials),F(0))<=H
    assert triples<=L
    assert all(abs(F(v))<=3*u*H+3*eta for v in partials[:-1])
    assert abs(sum(map(F,partials),F(0))-sum(map(F,ts),F(0)))<=L*(2*u*H+2*eta)
    n=len(partials);hi=0.0;correction=False;stopped=False;lo=0.0
    if n:
        n-=1;hi=partials[n]
        while n:
            x=hi;n-=1;y=partials[n];hi=x+y;yr=hi-x;lo=y-yr
            if lo:stopped=n>0;break
        if n and ((lo<0 and partials[n-1]<0) or (lo>0 and partials[n-1]>0)):
            y=lo+lo;x=hi+y;yr=x-hi
            if y==yr:correction=True;assert abs(F(x)-F(hi))<=8*u*G+8*eta;hi=x
    assert pack(hi)==pack(math.fsum(ts))
    assert abs(F(hi)-sum(map(F,ts),F(0)))<=fsum_error(p,A)
    return {'triples':triples,'early_tail':stopped,'correction':correction}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True);args=ap.parse_args()
    out=Path(args.output);assert not out.exists()
    binding=json.loads((RUN/'runtime_binding.json').read_text())
    assert sys.version==binding['python']
    for rec in binding['functions'].values():assert sha(rec['origin'])==rec['origin_sha256']
    probe=ctypes.CDLL(str(RUN/'fp_environment_probe.dylib'));probe.c1_read_fpcr.restype=ctypes.c_uint64
    assert probe.c1_read_fpcr()==0 and probe.c1_rounding()==probe.c1_nearest_constant()
    inequalities=[(u+3*u*u+u**3,2*u),(2+3*u+u*u,4),
                  (2*u+3*u*u+u**3,3*u),(3+3*u+u*u,6),
                  (1+3*u+3*u*u+u**3,1+4*u),(4+3*u+u*u,6),
                  (7*u+6*u*u,8*u),(F(13,2)+6*u,8)]
    assert all(a<=b for a,b in inequalities)
    limits=[]
    for p in [1,2,3,64,128,768,1024,2**20]:
        L,H,G=masses(p,F(4*p))
        assert 4*L*u<F(1,4096) and p*u<=F(1,2**33)
        assert 3*L*eta<1 and p*h<1 and H<2**23 and G<2**24
        alpha,beta=coefficients(p);assert alpha>=0 and beta>=0
        for A in [F(0),F(1,3),F(p),F(4*p)]:assert score_error(p,A)==alpha*A+beta
        limits.append({'p':p,'L':L,'alpha_approx':float(alpha),'beta_exact':str(beta),
                       'F_at_A_1_approx':float(fsum_error(p,F(1)))})
    rng=random.Random(2026111803)
    tiny=float(eta)
    vals=[0.,-0.,4.,-4.,1.,-1.,.5,-.5,tiny,-tiny,2**-1022,-2**-1022,
          2**-53,-2**-53,2**-54,-2**-54,math.nextafter(1.,0.),math.nextafter(1.,2.)]
    sequences=[[0.],[-0.],[tiny],[-tiny],[tiny,-tiny],[4.,-4.,tiny],
               [2**-107,2**-53,1.],[-2**-107,-2**-53,-1.],
               [1.,2**-53], [2**-1022,tiny,-2**-1022]]
    for p in [1,2,3,8,32,128,768]:
        for j in range(24):
            sequences.append([rng.choice(vals) if j%2 else math.ldexp(rng.uniform(-1,1),rng.randint(-1073,2)) for _ in range(p)])
    trace=[traced_fsum(t) for t in sequences]
    assert any(x['correction'] for x in trace) and any(x['early_tail'] for x in trace)
    # Exhaustive 2D support identities and canonical inequalities.
    grid=[-1.,0.,1.];intervals=[(a,b) for a in grid for b in grid if a<=b]
    box_count=0;oracle_pairs=0
    for box in itertools.product(intervals,repeat=2):
        for z in itertools.product(grid,repeat=2):
            for w in itertools.product(grid,repeat=2):
                bound=numeric_bound(box,z,w)
                corners=list(itertools.product(*[sorted(set(v)) for v in box]))
                support=sum((max(F(lo)*(F(a)-F(b)),F(hi)*(F(a)-F(b))) for (lo,hi),a,b in zip(box,z,w)),F(0))
                assert support==max(exact_dot(q,z)-exact_dot(q,w) for q in corners)
                for q in corners:
                    assert F(canonical(q,z))-F(canonical(q,w))<=bound;oracle_pairs+=1
                box_count+=1
    # Arbitrary finite guarded inputs are a superset of unit-norm E01 inputs.
    stress_pairs=0;stress_blocks=0;products=0
    for p in [1,2,3,8,32,128,768]:
        for j in range(12):
            qs=[[rng.uniform(-1,1) if j%2 else rng.choice(vals)/2 for _ in range(p)] for _ in range(6)]
            z=[rng.uniform(-1,1) for _ in range(p)];w=[rng.uniform(-1,1) for _ in range(p)]
            box=box_of(qs);bound=numeric_bound(box,z,w);stress_blocks+=1
            for q in qs:
                assert F(canonical(q,z))-F(canonical(q,w))<=bound
                for v in [z,w]:
                    A=sum((max(abs(F(lo)),abs(F(hi)))*abs(F(x)) for (lo,hi),x in zip(box,v)),F(0))
                    assert abs(F(canonical(q,v))-exact_dot(q,v))<=score_error(p,A)
                    products+=p
                stress_pairs+=1
    # Saved named cases, including unchanged historical failures of real-dot pruning.
    cases=[]
    def named(name,qs,z,w,expect):
        box=box_of(qs);c={'coordinates':0};bound=numeric_bound(box,z,w,counter=c)
        differences=[F(canonical(q,z))-F(canonical(q,w)) for q in qs]
        assert bound is not None and max(differences)<=bound and (bound<0)==expect
        assert c['coordinates']==len(z)
        cases.append({'name':name,'dimension':len(z),'q_count':len(qs),
          'q_hex':[[x.hex() for x in q] for q in qs], 'z_hex':[x.hex() for x in z],
          'w_hex':[x.hex() for x in w], 'bound_exact':str(bound), 'bound_display':float(bound),
          'canonical_differences':[str(d) for d in differences], 'certified':bound<0,
          'bound_coordinate_visits':c['coordinates'], 'scorer_calls_in_bound':0})
    named('rounded_products_tie',[[.6,.8]],[math.nextafter(.6,math.inf),math.nextafter(.8,-math.inf)],[.6,.8],False)
    named('subnormal_product_tie',[[1.,tiny]],[1.,0.],[1.,tiny],False)
    named('exact_tie',[[1.,0.]],[1.,0.],[1.,0.],False)
    named('negative_strict',[[1.,0.]],[-.8,.6],[-.6,.8],True)
    q=[399/401,40/401]
    named('C1_2d_old',[q],[.8,.6],[1.,0.],True)
    named('C1_2d_new',[q],[.8,-.6],[1.,0.],True)
    qs=[[.8,0.,.6],[99/101,20/101,0.]]
    named('C1_3d_old',qs,[.8,-.6,0.],[1.,0.,0.],True)
    named('C1_3d_new',qs,[.8,.6,0.],[1.,0.,0.],True)
    named('wide_box',[[1.,0.],[0.,1.]],[0.,1.],[1.,0.],False)
    named('768d_padding',[q+[0.]*766],[.8,.6]+[0.]*766,[1.,0.]+[0.]*766,True)
    # With fixed box, certificates have identical work regardless of query count.
    repeated=[q for _ in range(64)]
    named('block64_same_bound',repeated,[.8,.6],[1.,0.],True)
    assert cases[4]['bound_exact']==cases[-1]['bound_exact']
    # Explicit guard failures; no guard is treated as a successful certificate.
    bad=[([],[],[],True), ([(0.,1.)],[0.],[],True),
         ([(1.,0.)],[0.],[0.],True), ([(0.,math.inf)],[0.],[0.],True),
         ([(0.,1.)],[math.nan],[0.],True), ([(0.,1.)],[2.1],[0.],True),
         ([(0.,1.)],[0.],[0.],False)]
    assert all(numeric_bound(*args) is None for args in bad)
    # Shape guard precedes traversal, so this check uses a length-only sentinel.
    class TooLong:
        def __len__(self):return 2**20+1
        def __iter__(self):raise AssertionError('dimension guard must run first')
    assert numeric_bound(TooLong(),[],[]) is None
    assert 'canonical(' not in inspect.getsource(numeric_bound)
    # Revalidate unchanged semantic counterexamples and exact-prefix lemma; do not
    # rerun the obsolete conditional numeric checks or write their old reports.
    spec=importlib.util.spec_from_file_location('previous_reasoning',ROOT/'scripts/check_c1_e03_reasoning.py')
    prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)
    fixtures=prior.fixtures_and_oracle();finite=prior.finite_relation()
    assert probe.c1_read_fpcr()==0
    result={'article_id':'A','attempt_id':'E03_2026-11-18_03','all_checks_passed':True,
      'analytic_proof':'docs/numeric_certificate_C1.md', 'runtime_audit':'docs/fsum_runtime_audit_C1.md',
      'proof_is_not_inferred_from_test_counts':True, 'coefficient_inequalities':len(inequalities),
      'dimension_endpoint_checks':limits, 'fsum_lists':len(sequences),
      'triple_checks':sum(x['triples'] for x in trace),
      'lists_with_early_tail':sum(x['early_tail'] for x in trace),
      'lists_with_applied_correction':sum(x['correction'] for x in trace),
      'box_identities':box_count, 'box_corner_score_pairs':oracle_pairs,
      'stress_blocks':stress_blocks,'stress_query_pairs':stress_pairs,'rounded_products_checked':products,
      'named_cases':cases,'guard_failures_checked':len(bad)+1,
      'fixtures':fixtures,'finite_relation':finite,'fpcr_before_after':[0,probe.c1_read_fpcr()],
      'script_sha256':sha(__file__),'python':sys.version,
      'method_implemented':False,'performance_experiments_executed':False,'E04_started':False,
      'scope':'Local E03 numerical proof audit and logical regression, not an implementation/performance experiment.'}
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ['all_checks_passed','fsum_lists','triple_checks','lists_with_early_tail',
      'lists_with_applied_correction','box_identities','box_corner_score_pairs','stress_blocks','stress_query_pairs',
      'guard_failures_checked']}))
    print(json.dumps({'fixtures':fixtures['case_count'],'snapshots':fixtures['snapshot_count'],'finite_relation':finite}))
if __name__=='__main__':main()
