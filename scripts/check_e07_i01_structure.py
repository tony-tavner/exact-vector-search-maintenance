#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check exact partition equivalence and norm call-count change on all dev registries."""
import json,os,sys
from e05_common import ROOT,sha,dump_new
os.environ.update({k:'1' for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','VECLIB_MAXIMUM_THREADS']})
sys.path.insert(0,str(ROOT/'src'))
from pvldb_a import blocks as oldblocks,model as oldmodel
from pvldb_a_e07_i01 import blocks as newblocks,model as newmodel

def main():
    base=ROOT/'results/iterations/E07_2026-11-18_01';manifest=json.loads((base/'workload_manifest.json').read_text());records=[]
    for c in manifest['cases']:
        w=json.loads((ROOT/c['path']).read_text());oldq=oldmodel.parse_queries(w['queries']);newq=newmodel.parse_queries(w['queries'])
        for policy in ['kd','norm']:
            count=[0];fn=newblocks.norm2
            def counted(v):count[0]+=1;return fn(v)
            newblocks.norm2=counted
            try:
                need=policy=='norm';a,ma=oldblocks.build_blocks(oldq,64,policy);b,mb=newblocks.build_blocks(newq,64,policy,need_norm=need)
            finally:newblocks.norm2=fn
            assert ma==mb and len(a)==len(b)
            assert all(x.bid==y.bid and x.members==y.members and x.box==y.box for x,y in zip(a,b))
            if need:assert all(x.max_norm2==y.max_norm2 for x,y in zip(a,b)) and count[0]==len(newq)
            else:assert all(y.max_norm2 is None for y in b) and count[0]==0
            records.append({'family':c['family'],'queries':len(newq),'policy':policy,'blocks':len(b),'identical_membership_boxes':True,'new_norm_calls':count[0],'old_norm_calls_by_code':len(oldq)*(2 if need else 1),'required_norms_equal':True})
    dump_new(ROOT/'reports/e_stages/E07/E07_2026-11-18_01/I01_structure_validation.json',{'all_passed':True,'records':records,'source_sha256':sha(__file__),'E08_started':False})
    print(json.dumps({'families':14,'structural_cases':len(records),'all_passed':True}))
if __name__=='__main__':main()
