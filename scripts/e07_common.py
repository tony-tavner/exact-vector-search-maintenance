#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Independent replay with memoized canonical scalar scores, outside timing."""
import collections,copy,datetime,hashlib,json,math,struct
from e05_common import ROOT,sha,dump_new,replay_events,cold_vectors,prepared_workload
from pvldb_a.oracle import exact

def expected_fast(w):
    identity={};qidentity={};scores={};norms=set();validation_checks=0
    def register_doc(d):
        for f in d['fragments']:
            key=(d['doc_id'],f['fragment_id'],f['text_version']);v=tuple(float(x) for x in f['vector']);signature=(f.get('text'),v)
            if key in identity:assert identity[key]==signature
            else:
                assert len(v)==768 and all(math.isfinite(x) for x in v) and abs(math.fsum(x*x for x in v)-1)<1e-12
                identity[key]=signature
    for d in w['documents']:register_doc(d)
    for batch in w['batches']:
        for e in batch['events']:
            if e['op']=='put_document':register_doc(e['document'])
            elif e['op']=='put_fragment':register_doc({'doc_id':e['doc_id'],'fragments':[e['fragment']]})
    for q in w['queries']:
        v=tuple(q['vector']);assert len(v)==768 and abs(math.fsum(x*x for x in v)-1)<1e-12
        qidentity[q['query_id']]=v
    docs=copy.deepcopy(w['documents']);queries=w['queries'];answers=[];trace=[]
    def snapshot(ds,version):
        nonlocal validation_checks
        result={}
        for q in queries:
            when=datetime.date.fromisoformat(q['query_time']);qv=qidentity[q['query_id']];rows=[]
            for d in ds:
                m=d['metadata']
                if m.get('enabled') is not True or any(k not in m or m[k]!=v for k,v in q['filter'].items()):continue
                if not datetime.date.fromisoformat(m['valid_from'])<=when<datetime.date.fromisoformat(m['valid_to']):continue
                frags=[]
                for f in d['fragments']:
                    identity_key=(d['doc_id'],f['fragment_id'],f['text_version']);key=(q['query_id'],)+identity_key
                    if key not in scores:
                        fv=identity[identity_key][1];scores[key]=math.fsum(x*y for x,y in zip(qv,fv))
                    frags.append((scores[key],f))
                if not frags:continue
                score,f=min(frags,key=lambda x:(-x[0],x[1]['fragment_id'].encode('utf8')))
                rows.append((score,d['doc_id'],f['fragment_id'],f['text_version']))
            rows.sort(key=lambda x:(-x[0],x[1].encode('utf8')))
            result[q['query_id']]={'query_id':q['query_id'],'query_version':q['query_version'],'config_version':q['config_version'],'corpus_version':version,
                                  'ordered_hits':[[did,fid,ver] for _,did,fid,ver in rows[:q['k']]]}
        return result
    answers.append(snapshot(docs,w['corpus_version']))
    assert answers[0][queries[0]['query_id']]==exact(docs,queries[0],w['corpus_version']);validation_checks+=1
    for i,batch in enumerate(w['batches']):
        assert not batch.get('queries') and not batch.get('documents')
        old={d['doc_id']:d for d in docs};changed={e['document']['doc_id'] if e['op']=='put_document' else e['doc_id'] for e in batch['events']}
        docs=replay_events(docs,batch['events']);new={d['doc_id']:d for d in docs};out=snapshot(docs,batch['corpus_version'])
        cf=0
        for did in changed:
            a={f['fragment_id']:f for f in old.get(did,{}).get('fragments',[])};z={f['fragment_id']:f for f in new.get(did,{}).get('fragments',[])}
            cf+=sum(a.get(k)!=z.get(k) for k in a.keys()|z.keys())
        affected=sum(out[q]['ordered_hits']!=answers[-1][q]['ordered_hits'] for q in out)
        trace.append({'batch':i+1,'event_label':batch['event_label'],'changed_documents':len(changed),'old_documents':len(old),
            'changed_document_fraction':len(changed)/max(1,len(old)),'changed_fragment_records':cf,
            'changed_fragment_fraction':cf/max(1,sum(len(d['fragments']) for d in old.values())),
            'affected_hit_outputs':affected,'query_outputs':len(out),'affected_hit_fraction':affected/max(1,len(out))})
        answers.append(out)
        if i in [len(w['batches'])//2-1,len(w['batches'])-1]:
            assert out[queries[0]['query_id']]==exact(docs,queries[0],batch['corpus_version']);validation_checks+=1
    return {'outputs':answers,'trace':trace,'oracle':'Independent pure Python canonical math.fsum, memoized by immutable identity; no engine/scorer/pruning imports',
            'canonical_scalar_scores_computed':len(scores),'uncached_reference_crosschecks':validation_checks}
