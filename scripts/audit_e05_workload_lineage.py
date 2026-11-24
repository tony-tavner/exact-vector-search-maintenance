#!/usr/bin/env python3
"""Map frozen synthetic changes to real development source text; no timing."""
import collections, hashlib, json
from pathlib import Path
from e05_common import ROOT, dump_new, sha

def main():
    p=json.loads((ROOT/'protocol/pilot_v1.json').read_text());data=ROOT/'data/processed/onet29_3_v1'
    fragments=collections.defaultdict(list);queries=collections.defaultdict(list)
    for line in (data/'fragments.jsonl').read_text().splitlines():
        f=json.loads(line)
        if f['split']=='development':fragments[f['text']].append(f['fragment_id'])
    for line in (data/'queries.jsonl').read_text().splitlines():
        q=json.loads(line)
        if q['split']=='development':queries[q['query_text']].append(q['query_id'])
    rows=[];checks=[]
    for case in p['cases']:
        w=json.loads((ROOT/case['path']).read_text());targets=[]
        for d in w['documents']:
            for f in d['fragments']:targets.append(('initial',d['doc_id'],f))
        for b in w['batches']:
            for e in b['events']:
                if e['op']=='put_document':
                    for f in e['document']['fragments']:targets.append((b['corpus_version'],e['document']['doc_id'],f))
                if e['op']=='put_fragment':targets.append((b['corpus_version'],e['doc_id'],e['fragment']))
        for version,did,f in targets:
            assert f['text'] in fragments,(case['id'],f['fragment_id'])
            rows.append({'case_id':case['id'],'version':version,'target_document':did,'target_fragment':f['fragment_id'],
                'target_text_version':f['text_version'],'text_sha256':hashlib.sha256(f['text'].encode()).hexdigest(),
                'development_source_fragment_ids':sorted(fragments[f['text']]),
                'controlled_event':version!='initial'})
        assert all(q['query_text'] in queries for q in w['queries'])
        if case['id'].startswith('P01'):
            ep=next((ROOT/'results/pilot/E05_2026-11-18_01/expected').glob(case['id']+'_*.json'))
            expected=json.loads(ep.read_text());qid=w['queries'][0]['query_id']
            inserted=w['batches'][0]['events'][0]['document']['doc_id'];removed=w['batches'][1]['events'][0]['fragment_id']
            hits=[x[qid]['ordered_hits'] for x in expected['outputs']]
            checks.append({'case_id':case['id'],'cold_insert_is_actual_new_leader':hits[1][0][0]==inserted and hits[0][0][0]!=inserted,
                'deleted_fragment_was_actual_winner':hits[1][0][1]==removed,
                'new_representative_after_deletion':hits[2][0][1]!=removed})
    assert all(all(v for k,v in x.items() if k!='case_id') for x in checks)
    dump_new(ROOT/'reports/e_stages/E05/E05_2026-11-18_01/workload_lineage.json',{
        'protocol_sha256':sha(ROOT/'protocol/pilot_v1.json'),'all_texts_from_development_sources':True,
        'note':'Copied fragment metadata such as source_key/kind describes the original target fragment. This explicit mapping identifies the actual source of replacement text. Changes and changed applicability are synthetic, not real O*NET release deltas.',
        'rows':rows,'scenario_checks':checks,'E06_started':False})
    print(json.dumps({'lineage_entries':len(rows),'scenario_checks':checks,'all_development':True}))

if __name__=='__main__':main()
