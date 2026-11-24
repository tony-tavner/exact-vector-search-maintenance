"""Versioned development regrouping/trace grid. No held-out data, no network."""
import copy,gzip,hashlib,json,random
from pathlib import Path
from e05_common import ROOT,sha,dump_new,replay_events

A=ROOT/'reports/exploration/EX01_2026-11-18_01'
D=ROOT/'data/derived/EX01_2026-11-18_01'

def main():
    assert (A/'policy.json').exists()
    candidates=[]
    for p in sorted((ROOT/'results/iterations/E07_2026-11-18_01/workloads').glob('*.json')):
        w=json.loads(p.read_text())
        key=hashlib.sha256(('A-redesign-2026-11-18:'+w['case_id']).encode()).hexdigest()
        candidates.append((key,p,w))
    selected=sorted(candidates,key=lambda x:x[0])[:4]
    D.mkdir(parents=True,exist_ok=False)
    cases=[];source_hashes={};lineage={}
    for _,path,old in selected:
        source_hashes[str(path.relative_to(ROOT))]=sha(path)
        assert old['split']=='development'
        held=old['batches'][0]['events'][0]['document']
        raw=sorted(copy.deepcopy(old['documents']+[held]),key=lambda x:x['doc_id'].encode())
        family=old['case_id'].split('_')[-1]
        fragment_pool=[f for d in raw for f in d['fragments']]
        for group_size in [1,4]:
            grouped=[]
            for n in range(0,len(raw),group_size):
                parents=raw[n:n+group_size]
                did=parents[0]['doc_id'] if group_size==1 else f'ex01:bundle4:{family}:{n//group_size:03}'
                d={'doc_id':did,'metadata':copy.deepcopy(parents[0]['metadata']),
                   'fragments':[copy.deepcopy(f) for p in parents for f in p['fragments']],
                   'source_documents':[p['doc_id'] for p in parents],
                   'data_kind':'original grouping' if group_size==1 else 'synthetic composite role handbook; not an official O*NET document'}
                grouped.append(d)
                lineage[did]=d['source_documents']
            assert len(grouped)>=2
            for horizon in [100,1000]:
                cid=f'EX01_SOC_{family}_G{group_size}_T{horizon}'
                initial=copy.deepcopy(grouped[:-1]);held=copy.deepcopy(grouped[-1]);state=copy.deepcopy(initial)
                w={'schema_version':1,'case_id':cid,'split':'development','mode':'ready_vectors',
                   'corpus_version':cid+':0','documents':initial,'queries':copy.deepcopy(old['queries']),
                   'batches':[],'parameters':{'leaf_limit':64},'provenance':
                   'Local O*NET development texts/vectors unchanged; synthetic regrouping and events. No new real source, no semantic gold, ready vectors diagnostic only.'}
                for q in w['queries']:q['query_version']='EX01:'+q['query_id'];q['k']=5
                changes=[]
                def add(events,label):
                    nonlocal state
                    step=len(w['batches'])+1
                    previous={d['doc_id']:d for d in state}
                    state=replay_events(state,events);current={d['doc_id']:d for d in state}
                    touched={e.get('doc_id',e.get('document',{}).get('doc_id')) for e in events}
                    actual=0
                    for did in touched:
                        a={f['fragment_id']:f for f in previous.get(did,{}).get('fragments',[])}
                        b={f['fragment_id']:f for f in current.get(did,{}).get('fragments',[])}
                        actual+=sum(a.get(k,{}).get('vector')!=b.get(k,{}).get('vector') for k in a.keys()|b.keys())
                    changes.append({'batch':step,'label':label,'changed_vector_records':actual,'touched_documents':len(touched)})
                    w['batches'].append({'corpus_version':cid+':'+str(step),'event_label':label,'events':copy.deepcopy(events)})
                for cycle in range(horizon//10):
                    target=initial[cycle%len(initial)];did=target['doc_id'];base=copy.deepcopy(target['fragments'][0])
                    source=next(f for f in fragment_pool if f['text']!=base['text'])
                    def put(source_fragment=None):
                        f=copy.deepcopy(base);f['text_version']=cid+':v'+str(len(w['batches'])+1)
                        if source_fragment is not None:f['text']=source_fragment['text'];f['vector']=copy.deepcopy(source_fragment['vector'])
                        return {'op':'put_fragment','doc_id':did,'fragment':f}
                    add([{'op':'put_document','document':held}],'insert_held_group')
                    add([{'op':'metadata','doc_id':did,'changes':{'enabled':False}}],'disable')
                    add([{'op':'metadata','doc_id':did,'changes':{'enabled':True}}],'enable')
                    add([put()],'version_only')
                    add([put(source)],'replace_text_from_development_source')
                    add([put()],'restore_text')
                    add([{'op':'delete_fragment','doc_id':did,'fragment_id':base['fragment_id']}],'delete_fragment')
                    add([put()],'restore_fragment')
                    add([{'op':'delete_document','doc_id':held['doc_id']}],'delete_held_group')
                    add([{'op':'delete_fragment','doc_id':did,'fragment_id':base['fragment_id']},put()],'atomic_remove_reinsert_version')
                p=D/(cid+'.json');dump_new(p,w)
                cases.append({'id':cid,'family':family,'group_size':group_size,'horizon':horizon,
                              'path':str(p.relative_to(ROOT)),'sha256':sha(p),'initial_documents':len(initial),
                              'initial_fragments':sum(len(d['fragments']) for d in initial),'queries':len(w['queries']),
                              'event_changes':changes})
    dump_new(D/'manifest.json',{'id':'EX01-data-1.0','cases':cases,'source_hashes':source_hashes,
             'source_documents_by_bundle':lineage,'independent_new_corpora':0,'source_texts_or_embeddings_modified':False,
             'validation_final_used':False,'source_data_reorganized':True,'method':'deterministic consecutive-id bundles of1 or4 occupations',
             'policy_sha256':sha(A/'policy.json')})
    rng=random.Random('EX01-2026-11-18');schedule=[]
    for block in range(4):
        work=[(c,method) for c in cases for method in ['C1','B3_ALL_SCORES']]
        rng.shuffle(work)
        for order,(c,method) in enumerate(work):
            schedule.append({'run_id':f'b{block:02}_o{order:02}_{c["id"]}_{method}',
                             'block':block,'phase':'warmup' if block==0 else 'measured','case_id':c['id'],
                             'workload':c['path'],'method':method,'package':'pvldb_a_e07_i01'})
    dump_new(A/'schedule.json',{'policy_sha256':sha(A/'policy.json'),'data_manifest_sha256':sha(D/'manifest.json'),'runs':schedule})
    # Copy the validated timing wrapper, altering only labels and post-timer compression.
    old=ROOT/'scripts/run_e07_case.py';s=old.read_text()
    s=s.replace('import argparse,hashlib,','import gzip,argparse,hashlib,')
    s=s.replace('E07_DEVELOPMENT','EX01_DEVELOPMENT_SCREEN')
    s=s.replace("(out/'worker.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\\n')", "with gzip.open(out/'worker.json.gz','wt',encoding='utf-8') as raw:json.dump(result,raw,ensure_ascii=False,separators=(',',':'))")
    new=ROOT/'scripts/run_ex01_case.py';new.write_text(s)
    dump_new(A/'runner_adaptation.json',{'parent':str(old.relative_to(ROOT)),'parent_sha256':sha(old),'runner':str(new.relative_to(ROOT)),
             'runner_sha256':sha(new),'changes':['stage label','gzip import and compressed raw result after timing boundary'],
             'engine_or_numeric_changes':False})
    dump_new(A/'prepared.json',{'families':[w['case_id'] for _,p,w in selected],'cases':len(cases),'runs':len(schedule),
             'new_primary_sources':0,'new_independent_datasets':0,'new_E03_started':False})
    print(json.dumps({'cases':len(cases),'runs':len(schedule),'families':[w['case_id'] for _,p,w in selected]}))

if __name__=='__main__':main()
