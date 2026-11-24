#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit actual target-history denominators and development-only text lineage."""
import collections,json
from e05_common import ROOT,sha,dump_new,replay_events
OUT=ROOT/'results/iterations/E07_2026-11-18_01'

def main():
    D=ROOT/'data/processed/onet29_3_v1';docs=[json.loads(x) for x in (D/'documents.jsonl').read_text().splitlines() if json.loads(x)['split']=='development']
    queries=[json.loads(x) for x in (D/'queries.jsonl').read_text().splitlines() if json.loads(x)['split']=='development'];qmap={q['query_id']:q for q in queries}
    text_sources=collections.defaultdict(list)
    for d in docs:
        for f in d['fragments']:text_sources[f['text']].append(f['fragment_id'])
    allowed={d['doc_id'] for d in docs};manifest=json.loads((OUT/'workload_manifest.json').read_text());all_cases=[];lineage=[]
    for c in manifest['cases']:
        path=ROOT/c['path'];assert sha(path)==c['sha256'];w=json.loads(path.read_text());assert w['split']=='development' and len(w['batches'])==100
        assert {q['query_id'] for q in w['queries']}=={q['query_id'] for q in queries if q['occupation_family']==c['family']}
        assert all(q['k']==5 and q['query_text']==qmap[q['query_id']]['query_text'] and q['filter']==qmap[q['query_id']]['filter'] for q in w['queries'])
        def audit_doc(d):
            assert d['doc_id'] in allowed
            for f in d['fragments']:assert f['text'] in text_sources
        for d in w['documents']:audit_doc(d)
        state=w['documents'];steps=[]
        for i,b in enumerate(w['batches']):
            touched={e['document']['doc_id'] if e['op']=='put_document' else e['doc_id'] for e in b['events']};assert len(touched)==1 and touched<=allowed
            for e in b['events']:
                if e['op']=='put_document':audit_doc(e['document'])
                if e['op']=='put_fragment':
                    f=e['fragment'];assert f['text'] in text_sources
                    lineage.append({'case_id':c['id'],'batch':i+1,'target_fragment_id':f['fragment_id'],'actual_text_source_ids':text_sources[f['text']]})
            old={d['doc_id']:d for d in state};state=replay_events(state,b['events']);new={d['doc_id']:d for d in state};did=next(iter(touched))
            a={f['fragment_id']:f for f in old.get(did,{}).get('fragments',[])};z={f['fragment_id']:f for f in new.get(did,{}).get('fragments',[])}
            ids=a.keys()|z.keys();vector_changes=sum(a.get(k,{}).get('vector')!=z.get(k,{}).get('vector') for k in ids)
            text_changes=sum(a.get(k,{}).get('text')!=z.get(k,{}).get('text') for k in ids)
            record_changes=sum(a.get(k)!=z.get(k) for k in ids)
            steps.append({'batch':i+1,'label':b['event_label'],'touched_documents':1,'actual_document_payload_changed':old.get(did)!=new.get(did),
                'old_document_count':len(old),'old_fragment_count':sum(len(d['fragments']) for d in old.values()),
                'vector_add_delete_or_change_count':vector_changes,'text_add_delete_or_change_count':text_changes,'full_fragment_record_change_count':record_changes})
        all_cases.append({'case_id':c['id'],'family':c['family'],'queries':len(w['queries']),'steps':steps,
            'zero_vector_change_replacement_batches':[s['batch'] for s in steps if s['label']=='replace_fragment_text_vector' and s['vector_add_delete_or_change_count']==0]})
    dump_new(OUT/'workload_audit.json',{'all_passed':True,'families':len(all_cases),'histories':all_cases,'fragment_lineage':lineage,
        'all_inputs_development':True,'all_family_queries_present':True,'E08_started':False,
        'note':'Labels describe intended event operation; actual vector/text/record changes are counted separately. Source metadata originally attached to the target is not claimed as provenance of substituted text; lineage identifies its real development sources.'})
    print(json.dumps({'families':len(all_cases),'batches':sum(len(c['steps']) for c in all_cases),'lineage_records':len(lineage),'all_passed':True}))
if __name__=='__main__':main()
