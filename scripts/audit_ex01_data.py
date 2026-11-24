"""Audit provenance and derived workload boundaries without using holdout content."""
import collections, json, math, struct
from e05_common import ROOT, sha, dump_new

A=ROOT/'reports/exploration/EX01_2026-11-18_01'
D=ROOT/'data/derived/EX01_2026-11-18_01'

def pair(f):return f['text'],struct.pack('='+str(len(f['vector']))+'d',*f['vector'])

def main():
    m=json.loads((D/'manifest.json').read_text());policy=json.loads((A/'policy.json').read_text())
    assert m['policy_sha256']==sha(A/'policy.json')
    assert not m['validation_final_used'] and m['independent_new_corpora']==0
    originals={}
    for path,h in m['source_hashes'].items():
        assert sha(ROOT/path)==h
        w=json.loads((ROOT/path).read_text());assert w['split']=='development'
        originals[w['case_id'].split('_')[-1]]=w
    expected_labels=['insert_held_group','disable','enable','version_only','replace_text_from_development_source',
                     'restore_text','delete_fragment','restore_fragment','delete_held_group','atomic_remove_reinsert_version']
    results=[]
    for c in m['cases']:
        assert sha(ROOT/c['path'])==c['sha256'];w=json.loads((ROOT/c['path']).read_text())
        assert w['mode']=='ready_vectors' and w['split']=='development' and len(w['batches'])==c['horizon']
        old=originals[c['family']]
        raw=sorted(old['documents']+[old['batches'][0]['events'][0]['document']],key=lambda d:d['doc_id'].encode())
        original_by_id={d['doc_id']:d for d in raw};allowed_pairs={pair(f) for d in raw for f in d['fragments']}
        all_docs=w['documents']+[w['batches'][0]['events'][0]['document']]
        assert len({d['doc_id'] for d in all_docs})==len(all_docs)
        assert sorted(x for d in all_docs for x in d['source_documents'])==sorted(original_by_id)
        expected_groups=[raw[n:n+c['group_size']] for n in range(0,len(raw),c['group_size'])]
        assert [[d['doc_id'] for d in g] for g in expected_groups]==[d['source_documents'] for d in all_docs]
        for d in all_docs:
            parents=[original_by_id[x] for x in d['source_documents']]
            assert d['metadata']==parents[0]['metadata']
            assert d['fragments']==[f for parent in parents for f in parent['fragments']]
            assert m['source_documents_by_bundle'][d['doc_id']]==d['source_documents']
        assert len(w['queries'])==len(old['queries'])==c['queries']
        for q,oq in zip(w['queries'],old['queries']):
            assert q['k']==oq['k']==5 and q['query_version']=='EX01:'+q['query_id']
            assert {k:v for k,v in q.items() if k!='query_version'}=={k:v for k,v in oq.items() if k!='query_version'}
        event_labels=[];events=collections.Counter();nonoriginal_pairs=0
        for i,b in enumerate(w['batches']):
            assert b['corpus_version']==c['id']+':'+str(i+1)
            assert b['event_label']==expected_labels[i%10];event_labels.append(b['event_label'])
            for e in b['events']:
                events[e['op']]+=1
                fs=e.get('document',{}).get('fragments',[]) if e['op']=='put_document' else [e['fragment']] if e['op']=='put_fragment' else []
                for f in fs:assert pair(f) in allowed_pairs
        assert all(n==c['horizon']//10 for n in collections.Counter(event_labels).values())
        results.append({'case_id':c['id'],'status':'passed','original_documents':len(raw),
                        'derived_documents_with_held_group':len(all_docs),'original_fragments':sum(len(d['fragments']) for d in raw),
                        'queries':len(w['queries']),'snapshots':len(w['batches'])+1,
                        'event_counts':dict(events),'event_label_counts':dict(collections.Counter(event_labels)),
                        'source_text_vector_pairs_preserved':True,'query_contract_preserved':True,
                        'new_independent_observations':False})
    dump_new(A/'data_audit.json',{'status':'passed','cases':results,'checked_cases':len(results),
        'source_paths':list(m['source_hashes']),'holdout_content_parsed':False,'network_used':False,
        'meaning':'Finite provenance/structure audit plus separately verified exact replay; not validation of realistic release changes or semantic labels.'})
    print(json.dumps({'status':'passed','cases':len(results),'independent_new_corpora':0}))

if __name__=='__main__':main()
