#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Freeze 100-batch, all-query development histories before E07 measurements."""
import copy,json,collections
from pathlib import Path
from e05_common import ROOT,sha,dump_new,replay_events
import numpy as np
A=ROOT/'reports/e_stages/E07/E07_2026-11-18_01'
OUT=ROOT/'results/iterations/E07_2026-11-18_01'

def main():
    policy=ROOT/'protocol/improvement_policy.json';p=json.loads(policy.read_text())
    # Correct a total-count arithmetic typo before any workload, code variant or timing.
    dump_new(A/'improvement_policy_preflight_v1.json',p)
    p['version']='A-E07-policy-1.1';p['research_budget']['primary_I01_runs']=360
    p['revision']='Only planned run-count arithmetic corrected 354->360; schedule/rules unchanged, before any timing.'
    policy.write_text(json.dumps(p,ensure_ascii=False,indent=2)+'\n')
    OUT.mkdir(parents=True,exist_ok=False)
    D=ROOT/'data/processed/onet29_3_v1';index=[json.loads(x) for x in (D/'embeddings_development/index.jsonl').read_text().splitlines()]
    assert all(x['split']=='development' for x in index)
    vectors=np.load(D/'embeddings_development/vectors.npy',allow_pickle=False)
    vi={(x['kind'],x['id']):vectors[x['row']].tolist() for x in index}
    docs=[json.loads(x) for x in (D/'documents.jsonl').read_text().splitlines() if json.loads(x)['split']=='development']
    queries=[json.loads(x) for x in (D/'queries.jsonl').read_text().splitlines() if json.loads(x)['split']=='development']
    for d in docs:
        for f in d['fragments']:f['vector']=vi['fragment',f['fragment_id']]
    for q in queries:q['vector']=vi['query',q['query_id']]
    cases=[];lineage=[]
    for family in sorted({d['occupation_family'] for d in docs}):
        ds=sorted([d for d in docs if d['occupation_family']==family],key=lambda d:d['doc_id'].encode('utf8'))
        qs=sorted([q for q in queries if q['occupation_family']==family],key=lambda q:q['query_id'].encode('utf8'))
        cid='T100_SOC_'+family;held=copy.deepcopy(ds[-1]);initial=copy.deepcopy(ds[:-1]);state=copy.deepcopy(initial)
        w={'schema_version':1,'case_id':cid,'split':'development','mode':'cold','corpus_version':cid+':0',
           'documents':initial,'queries':copy.deepcopy(qs),'batches':[],'parameters':{'leaf_limit':64},
           'provenance':'Existing O*NET 29.3 development sources; synthetic single-document atomic updates, no real release delta or semantic gold.',
           'target_contract':{'k':5,'atomic_batches':100,'registry':'all family queries','reads':'each active query once per scheduled read'}}
        for q in w['queries']:q['k']=5;q['query_version']='E07-target-v1:'+family
        def add(events,label):
            nonlocal state
            step=len(w['batches'])+1
            touched={e['document']['doc_id'] if e['op']=='put_document' else e['doc_id'] for e in events};assert len(touched)==1
            w['batches'].append({'corpus_version':cid+':'+str(step),'event_label':label,'events':copy.deepcopy(events)})
            state=replay_events(state,events)
        for cycle in range(10):
            target=initial[cycle%len(initial)];did=target['doc_id'];base=copy.deepcopy(target['fragments'][0]);source=ds[(cycle+1)%len(ds)]['fragments'][0]
            def put_fragment(text=None,vector=None):
                f=copy.deepcopy(base);f['text_version']=cid+':fragment:'+str(len(w['batches'])+1)
                if text is not None:f['text']=text;f['vector']=copy.deepcopy(vector)
                return {'op':'put_fragment','doc_id':did,'fragment':f}
            add([{'op':'put_document','document':held}],'insert_held_document')
            add([{'op':'metadata','doc_id':did,'changes':{'enabled':False}}],'disable_applicability')
            add([{'op':'metadata','doc_id':did,'changes':{'enabled':True}}],'restore_applicability')
            add([put_fragment()],'text_version_only')
            replacement=put_fragment(source['text'],source['vector']);add([replacement],'replace_fragment_text_vector')
            lineage.append({'case_id':cid,'batch':len(w['batches']),'target_doc_id':did,'target_fragment_id':base['fragment_id'],'source_fragment_id':source['fragment_id'],'source_family':family,'split':'development'})
            add([put_fragment()],'restore_fragment_text_vector')
            add([{'op':'delete_fragment','doc_id':did,'fragment_id':base['fragment_id']}],'delete_first_fragment')
            add([put_fragment()],'restore_deleted_fragment')
            add([{'op':'delete_document','doc_id':held['doc_id']}],'delete_held_document')
            add([{'op':'delete_fragment','doc_id':did,'fragment_id':base['fragment_id']},put_fragment()],'atomic_remove_reinsert_fragment_version')
        assert len(w['batches'])==100 and all(q['k']==5 for q in w['queries'])
        path=OUT/'workloads'/(cid+'.json');dump_new(path,w)
        cases.append({'id':cid,'family':family,'path':str(path.relative_to(ROOT)),'sha256':sha(path),'initial_documents':len(initial),
            'initial_fragments':sum(len(d['fragments']) for d in initial),'queries':len(qs),'batches':100,'k':5,
            'mode':'cold','selection':'all development families for headroom','comparison_selected':family in ['27','25']})
    existing=json.loads((ROOT/'protocol/pilot_v1.json').read_text())['cases']
    regressions=[c for c in existing if c['id'] in p['comparison']['ready_regressions']]
    dump_new(OUT/'workload_manifest.json',{'cases':cases,'ready_regressions':regressions,'lineage':lineage,'policy_sha256':sha(policy),
        'generator_sha256':sha(__file__),'event_mix':dict(collections.Counter(b['event_label'] for b in w['batches'])),
        'known_limitation':'Replacement source texts already occur within the family; within-run embedding reuse is intentionally charged and reported. Future unseen texts can reduce engine-saving headroom. Histories cover allowed event types but do not establish the final suite.',
        'validation_or_final_accessed':False,'E08_started':False})
    print(json.dumps({'families':len(cases),'histories_batches_each':100,'comparison_families':['27','25'],'E08_started':False}))

if __name__=='__main__':main()
