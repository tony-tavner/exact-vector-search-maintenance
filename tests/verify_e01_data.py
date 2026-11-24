"""Validate E01 data contracts and deterministic preparation; not a benchmark."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np

ROOT=Path(__file__).resolve().parents[1]

def load_lines(p):return [json.loads(x) for x in p.read_text().splitlines()]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True);a=ap.parse_args()
    prepared=ROOT/'data/processed/onet29_3_v1';emb=prepared/'embeddings_development'
    docs=load_lines(prepared/'documents.jsonl');fs=load_lines(prepared/'fragments.jsonl')
    queries=load_lines(prepared/'queries.jsonl');idx=load_lines(emb/'index.jsonl')
    splits=json.loads((prepared/'splits.json').read_text());quality=json.loads((prepared/'quality_report.json').read_text())
    vectors=np.load(emb/'vectors.npy',allow_pickle=False)
    assert vectors.shape==(1943,768) and vectors.dtype==np.float64
    assert np.isfinite(vectors).all() and np.max(abs(np.sum(vectors*vectors,axis=1)-1))<1e-12
    assert len({x['id'] for x in idx})==len(idx)
    assert all(x['split']=='development' for x in idx)
    assert not (prepared/'embeddings_final_holdout').exists()
    assert not splits['holdout_policy']['used_for_method_selection']
    assert len({d['doc_id'] for d in docs})==1016
    assert len({f['fragment_id'] for f in fs})==1895
    sets=[set(v) for v in splits['documents'].values()]
    assert all(not x.intersection(y) for i,x in enumerate(sets) for y in sets[i+1:])
    for d in docs:
        assert d['doc_id'] in splits['documents'][d['split']]
        assert splits['group_to_split'][d['occupation_family']]==d['split']
        assert 'synthetic' in d['metadata']['provenance']
    for q in queries:
        assert not q['semantic_gold'] and q['split']==splits['group_to_split'][q['occupation_family']]
    for w in load_lines(prepared/'controlled_workloads.jsonl'):
        valid=set(splits['documents'][w['split']])
        assert set(w['initial_doc_ids'])<=valid
        assert all(e['doc_id'] in valid for e in w['events'])
        assert not w['executed']
    ratings=load_lines(prepared/'skill_ratings.jsonl')
    assert len(ratings)==61530 and sum(x['recommend_suppress']=='Y' for x in ratings)==124
    assert sum(len(d['fragments'])==1 for d in docs)==137
    # Rebuild in an isolated local directory and compare deterministic products.
    with tempfile.TemporaryDirectory(prefix='e01_rebuild_',dir=ROOT/'reports/e_stages/E01') as tmp:
        dest=Path(tmp)/'prepared'
        cmd=[sys.executable,str(ROOT/'scripts/prepare_data.py'),'build','--out',str(dest)]
        proc=subprocess.run(cmd,text=True,capture_output=True)
        assert proc.returncode==0,proc.stderr
        compared=[]
        for p in sorted(dest.iterdir()):
            assert sha(p)==sha(prepared/p.name),p.name
            compared.append({'file':p.name,'sha256':sha(p)})
    # Test the real development representation through a separate exact snapshot oracle.
    spec=importlib.util.spec_from_file_location('fixture_oracle',ROOT/'tests/verify_e01_fixtures.py')
    oracle=importlib.util.module_from_spec(spec);spec.loader.exec_module(oracle)
    vector_map={x['id']:vectors[x['row']].tolist() for x in idx}
    dev=[json.loads(json.dumps(d)) for d in docs if d['split']=='development']
    for d in dev:
        for f in d['fragments']:f['vector']=vector_map[f['fragment_id']]
    chosen=[];seen=set()
    for q in queries:
        if q['split']=='development' and q['occupation_family'] not in seen:
            chosen.append(dict(q,vector=vector_map[q['query_id']]))
            seen.add(q['occupation_family'])
        if len(chosen)==6:break
    observations=[]
    for q in chosen:
        exact=oracle.exact(dev,q,'onet29.3-controlled-v1')
        rows=[]
        for d in dev:
            if d['metadata']['role']!=q['filter']['role']:continue
            # Independent vectorized reference; compare ordered identifiers, not merely norms.
            matrix=np.asarray([f['vector'] for f in d['fragments']])
            scores=matrix@np.asarray(q['vector'])
            pairs=[(-float(score),f['fragment_id'].encode(),f) for score,f in zip(scores,d['fragments'])]
            winner=min(pairs,key=lambda x:x[:2]);f=winner[2]
            rows.append((winner[0],d['doc_id'].encode(),[d['doc_id'],f['fragment_id'],f['text_version']]))
        independent=[x[2] for x in sorted(rows,key=lambda x:x[:2])[:q['k']]]
        assert independent==exact['ordered_hits'],q['query_id']
        observations.append({'query_id':q['query_id'],'scope':'development only, computational answer; not semantic gold','answer':exact,'independent_numpy_order_matches':True})
    report={'passed':True,'source_occupations':len(docs),'source_skill_rows':len(ratings),
            'fragments':len(fs),'synthetic_queries':len(queries),'development_vectors':len(idx),
            'split_counts':quality['split_documents'],'disjoint_family_splits':True,
            'suppressed_rows_preserved':124,'missing_skill_profiles_retained':137,
            'rebuild_identical_files':compared,'real_data_oracle_checks':observations,
            'holdout_retrieval_evaluated':False,'method_comparison_executed':False,
            'scope':'Data readiness validation only; no proposed algorithm, novelty or efficiency claim.'}
    Path(a.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['rebuild_identical_files','real_data_oracle_checks']},ensure_ascii=False))

if __name__=='__main__':main()
