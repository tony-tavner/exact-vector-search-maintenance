#!/usr/bin/env python3
"""Paid, separate exact diagnosis of rejected C1 cells; not an optimization."""
import json, math, os, sys
from fractions import Fraction as F
from e05_common import ROOT, sha, dump_new
os.environ.update({k:'1' for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','VECLIB_MAXIMUM_THREADS']})
sys.path.insert(0,str(ROOT/'src'))
from pvldb_a import engine as en
from pvldb_a.model import applicable

A=ROOT/'reports/e_stages/E06/E06_2026-11-18_01'
OUT=ROOT/'results/comparison/E06_2026-11-18_01'

def main():
    cases=['P03_ready_local_11','P07_ready_scale_128','P08_memory_headroom_256']
    dump_new(A/'geometry_protocol.json',{'version':'A-E06-geometry-1.0','cases':cases,'script_sha256':sha(__file__),
        'purpose':'Distinguish loose block bound, fixed-witness restriction, and true changed document maxima after a rejected cell. Uses all queries, separately reports eligible queries. No speed measurement or new algorithm.',
        'development_only':True,'E07_started':False})
    orig_cover=en.Engine._cover;orig_bounds=en.bounds;cell_bounds=[];records=[];phase=[None]
    def observed_bounds(box,z,w=None,context=None,counters=None,separate=False):
        value=orig_bounds(box,z,w,context,counters,separate)
        if w is not None:
            support=sum((max(F(lo)*(F(a)-F(b)),F(hi)*(F(a)-F(b))) for (lo,hi),a,b in zip(box,z,w)),F(0))
            cell_bounds.append({'bound_sign':None if value is None else (-1 if value<0 else 0 if value==0 else 1),
                                'exact_support_sign':-1 if support<0 else 0 if support==0 else 1,
                                'bound_approx':None if value is None else float(value),'support_approx':float(support)})
        return value
    en.bounds=observed_bounds
    def cover(self,old,new,block,m,cache=None,oldroot=None):
        cell_bounds.clear();result=orig_cover(self,old,new,block,m,cache,oldroot)
        if old is None or new is None or old.metadata!=new.metadata:return result
        af={f.fid:f for f in old.fragments};bf={f.fid:f for f in new.fragments}
        common={k for k in af if k in bf and af[k].text is not None and af[k].identity==bf[k].identity}
        if not common:return result
        delta=[f for f in old.fragments if f.fid not in common]+[f for f in new.fragments if f.fid not in common]
        if not delta:return result
        witness=af[min(common,key=lambda x:x.encode('utf8'))];query_checks=[]
        for qid in block.members:
            q=oldroot.queries[qid]
            def score(f):return math.fsum(x*y for x,y in zip(q.v,f.v))
            scores_a={f.fid:score(f) for f in old.fragments};scores_b={f.fid:score(f) for f in new.fragments}
            sw=scores_a[witness.fid]
            fixed=all((scores_a[f.fid] if any(f is x for x in old.fragments) else scores_b[f.fid])<sw for f in delta)
            def row(d,scores):
                f=min(d.fragments,key=lambda f:(-scores[f.fid],f.fid.encode('utf8')))
                return (scores[f.fid],f.fid,f.version)
            query_checks.append({'query_id':qid,'applicable':applicable(q,new),'fixed_witness_strictly_dominates':fixed,
                                 'document_row_identical':row(old,scores_a)==row(new,scores_b)})
        valid=all(q['fixed_witness_strictly_dominates'] for q in query_checks)
        same=all(q['document_row_identical'] for q in query_checks)
        kind='certified' if result else 'loose_bound' if valid else 'fixed_witness_restriction' if same else 'some_document_row_changed'
        if result:assert valid and same
        records.append({'case_id':phase[0],'batch':phase[1],'document_id':old.did,'members':len(block.members),
            'certified':result,'classification':kind,'query_checks':query_checks,'attempted_bounds':list(cell_bounds),
            'all_eligible_rows_identical':all(q['document_row_identical'] for q in query_checks if q['applicable']),
            'eligible_queries':sum(q['applicable'] for q in query_checks)})
        return result
    en.Engine._cover=cover
    protocol=json.loads((ROOT/'protocol/pilot_v1.json').read_text());runs=[]
    for cid in cases:
        c=next(c for c in protocol['cases'] if c['id']==cid);w=json.loads((ROOT/c['path']).read_text())
        assert w['mode']=='ready_vectors' and w['split']=='development'
        e=en.Engine('C1',**w.get('parameters',{}));e.build(w['documents'],w['queries'],w['corpus_version']);outputs=[e.answers()];v=w['corpus_version']
        for i,b in enumerate(w['batches']):
            phase[:]=[cid,i+1];e.apply(b['events'],b['corpus_version'],v);v=b['corpus_version'];outputs.append(e.answers())
        prior=json.loads((OUT/'profiles'/('E06_diag_v1_'+cid+'_C1')/'profile.json').read_text())
        assert outputs==prior['outputs'] and e.ctx.bound and sys.gettrace() is None and sys.getprofile() is None
        runs.append({'case_id':cid,'workload_sha256':sha(ROOT/c['path']),'full_outputs_match':True,'numeric_guards_enabled':True})
    dump_new(OUT/'geometry_audit.json',{'records':records,'runs':runs,'E07_started':False,'performance_claim':False})
    from collections import Counter
    print(json.dumps({'cells':len(records),'classifications':dict(Counter(r['classification'] for r in records)),'E07_started':False}))

if __name__=='__main__':main()
