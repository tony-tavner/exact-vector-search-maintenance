"""Prepare an O*NET snapshot and controlled workloads, using local files only.

Does not implement the proposed incremental method or compare algorithms.
Existing output directories are immutable: select a new output version for changes.
"""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
SOURCE_HASHES={
    'onet_occupations.tsv':'63e6029d3d30ff5c7cf39b5304a733b77a409e01c65ae7095fe92f6d18d74a66',
    'onet_skills.tsv':'52e042e9cfc3352a2da28a39a164cfd8244267e9fd3d0ee027c2d4228919e23d',
}
CONFIG='nomic-137m-f16-970aa74c-llama11146-mean-prefix-f64-v1'
SPLIT_SEED='pvldb-A-e01-soc-major-v1'

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def write_json(p,obj):
    Path(p).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def write_lines(p,rows):
    Path(p).write_text(''.join(json.dumps(r,ensure_ascii=False,allow_nan=False)+'\n' for r in rows))

def read_table(p):
    with p.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f,delimiter='\t')
        return reader.fieldnames,list(reader)

def build(raw,out):
    if out.exists():raise ValueError('Output already exists; choose a new version, do not overwrite.')
    for name,expected in SOURCE_HASHES.items():
        if sha(raw/name)!=expected:raise ValueError('Unexpected raw file hash: '+name)
    occ_cols,occupations=read_table(raw/'onet_occupations.tsv')
    skill_cols,skills=read_table(raw/'onet_skills.tsv')
    assert occ_cols==['O*NET-SOC Code','Title','Description']
    assert len(occupations)==1016 and len(skills)==61530
    codes=[x['O*NET-SOC Code'] for x in occupations]
    assert len(codes)==len(set(codes))
    assert all(re.fullmatch(r'\d{2}-\d{4}\.\d{2}',c) for c in codes)
    assert all(r['Title'].strip() and r['Description'].strip() for r in occupations)
    assert all(set(r)==set(occ_cols) for r in occupations)
    by_occ=defaultdict(list);keys=set();suppressed=0
    for r in skills:
        assert r['O*NET-SOC Code'] in codes
        key=(r['O*NET-SOC Code'],r['Element ID'],r['Scale ID'])
        assert key not in keys;keys.add(key)
        assert r['Scale ID'] in ['IM','LV']
        value=float(r['Data Value']);assert math.isfinite(value)
        assert 0<=value<=(5 if r['Scale ID']=='IM' else 7)
        assert r['Recommend Suppress'] in ['Y','N']
        suppressed+=r['Recommend Suppress']=='Y'
        by_occ[r['O*NET-SOC Code']].append(r)
    groups=sorted({c[:2] for c in codes},key=lambda g:hashlib.sha256((SPLIT_SEED+':'+g).encode()).hexdigest())
    group_to_split={g:('development' if i<14 else 'validation' if i<18 else 'final_holdout') for i,g in enumerate(groups)}
    docs=[];fragments=[];queries=[];edges=[]
    for r in sorted(occupations,key=lambda x:x['O*NET-SOC Code']):
        code=r['O*NET-SOC Code'];doc_id='onet29.3:'+code;group=code[:2];split=group_to_split[group]
        texts=[('description',r['Title']+'. '+r['Description'])]
        sr=by_occ.get(code,[])
        names={row['Element ID']:row['Element Name'] for row in sr}
        if names:
            texts.append(('skills',r['Title']+'. O*NET skill categories (not individual qualifications): '+
                          '; '.join(names[k] for k in sorted(names))+'.'))
        fs=[]
        for kind,text in texts:
            text=' '.join(text.split())
            fid=doc_id+':'+kind
            version='onet29.3-'+hashlib.sha256(text.encode()).hexdigest()[:16]
            f={'fragment_id':fid,'text_version':version,'text':text,'kind':kind,
               'source_file':'onet_occupations.tsv' if kind=='description' else 'onet_skills.tsv',
               'source_key':code,'source_kind':'real_public_occupation_data',
               'transformation':'title plus source description' if kind=='description' else 'title plus all sorted unique listed skill names; no rating-based selection'}
            fs.append(f)
            fragments.append(dict(f,doc_id=doc_id,split=split,embedding_id=fid))
        metadata={'role':'soc_major_'+group,'equipment':'generic','language':'en','access_scope':'public',
                  'enabled':True,'valid_from':'2026-01-01','valid_to':'2027-01-01',
                  'provenance':'ALL applicability fields are controlled synthetic workload metadata, not O*NET legal applicability.'}
        docs.append({'doc_id':doc_id,'corpus_version':'onet29.3-controlled-v1','occupation_code':code,
                     'occupation_family':group,'split':split,'metadata':metadata,'fragments':fs})
        query_text='What skills and responsibilities are relevant to the occupation '+r['Title']+'?'
        queries.append({'query_id':'query:'+code,'query_version':'v1','query_text':query_text,
                        'query_time':'2026-11-17','k':5,'filter':{'role':'soc_major_'+group,'equipment':'generic','language':'en','access_scope':'public'},
                        'split':split,'occupation_family':group,'config_version':CONFIG,
                        'source_kind':'synthetic_template_query','semantic_gold':False,
                        'purpose':'computational maintenance workload, not expert relevance evaluation'})
        for row in sr:
            edges.append({'doc_id':doc_id,'element_id':row['Element ID'],'element_name':row['Element Name'],
                          'scale_id':row['Scale ID'],'value':float(row['Data Value']),
                          'recommend_suppress':row['Recommend Suppress'],'not_relevant':row['Not Relevant'],
                          'observation_date':row['Date'],'domain_source':row['Domain Source']})
    split_obj={'schema_version':1,'version':'soc-major-v1','seed':SPLIT_SEED,
               'assignment':'sort SHA256(seed:major_group); first 14 development, next 4 validation, last 5 final_holdout',
               'unit':'O*NET SOC major family; all occupations/fragments/queries/controlled versions of a family stay together',
               'group_to_split':dict(sorted(group_to_split.items())),
               'documents':{s:[d['doc_id'] for d in docs if d['split']==s] for s in ['development','validation','final_holdout']},
               'holdout_policy':{'content_prepared':True,'metadata_audited':True,'retrieval_outcomes_examined':False,
                                 'used_for_method_selection':False,'semantic_queries_expert_validated':False,
                                 'note':'Prepared holdout is not a separate external dataset; no claim of complete semantic independence.'}}
    dup=defaultdict(set)
    for f in fragments:dup[hashlib.sha256(f['text'].encode()).hexdigest()].add(f['split'])
    cross=[h for h,parts in dup.items() if len(parts)>1]
    assert not cross,'Identical fragment text crosses splits'
    out.mkdir(parents=True)
    write_lines(out/'documents.jsonl',docs);write_lines(out/'fragments.jsonl',fragments)
    write_lines(out/'queries.jsonl',queries);write_lines(out/'skill_ratings.jsonl',edges)
    write_json(out/'splits.json',split_obj)
    workloads=[]
    for split,ids in split_obj['documents'].items():
        ids=sorted(ids);withheld=ids[-1];first=ids[0]
        events=[{'event_id':split+':insert','operation':'insert_document','doc_id':withheld},
                {'event_id':split+':delete_fragment','operation':'delete_fragment','doc_id':first,'fragment_id':first+':description'},
                {'event_id':split+':disable','operation':'update_metadata','doc_id':ids[1],'changes':{'enabled':False}},
                {'event_id':split+':restore','operation':'update_metadata','doc_id':ids[1],'changes':{'enabled':True}},
                {'event_id':split+':delete_document','operation':'delete_document','doc_id':ids[2]},
                {'event_id':split+':text_version','operation':'revise_text_version_same_content','doc_id':ids[3],'fragment_id':ids[3]+':description','new_version':'controlled-v2'}]
        workloads.append({'split':split,'scenario_id':'controlled-sequence-v1:'+split,'initial_doc_ids':[x for x in ids if x!=withheld],
                          'catalog_snapshot':'documents.jsonl','events':events,
                          'provenance':'Artificial temporal arrivals/deletions/metadata/version changes over one real O*NET release; not observed historical deltas.',
                          'executed':False,'expected_answers':'To be produced by fixed exact operator for future experiments; no semantic gold.'})
    write_lines(out/'controlled_workloads.jsonl',workloads)
    stats={'occupations':len(docs),'fragments':len(fragments),'queries':len(queries),'skill_rows':len(skills),
           'occupations_with_skills':len(by_occ),'occupations_without_skills':len(docs)-len(by_occ),
           'unique_skills':len({r['Element ID'] for r in skills}),'suppressed_rating_rows':suppressed,
           'suppressed_policy':'Retained and flagged in skill_ratings; no statistical rating-based filtering.',
           'occupation_groups':len(groups),'split_documents':{k:len(v) for k,v in split_obj['documents'].items()},
           'split_fragments':dict(Counter(f['split'] for f in fragments)),
           'duplicate_occupation_codes':0,'duplicate_skill_keys':0,'unknown_skill_occupation_codes':0,
           'cross_split_identical_fragment_texts':len(cross),'max_fragment_characters':max(len(f['text']) for f in fragments),
           'source_snapshot_only':True,'real_historical_deltas':False,'expert_semantic_labels':False,
           'all_metadata_fields_synthetic':True,'scientific_experiments_executed':False}
    write_json(out/'quality_report.json',stats)
    config={'config_version':CONFIG,'model':'nomic-embed-text:137M:F16',
            'weights_sha256':'970aa74c0a90ef7482477cf803618e776e173c007bf957f635f1015bfcfef0e6',
            'weights_local_path':'data/raw/models/nomic_embed_text/weights.gguf','dimension':768,
            'runtime':'llama.cpp 0.5.0 build 11146 commit 7fe450e19','pooling':'mean',
            'document_prefix':'search_document: ','query_prefix':'search_query: ',
            'prefix_basis':'Explicit fixed preprocessing choice; semantic quality is not established by E01.',
            'context':2048,'threads':4,'gpu_layers':0,'offline':True,
            'normalization':'runtime L2; JSON output parsed as float64 and L2-renormalized with math.fsum',
            'score_policy':'math.fsum(q_i*x_i), Python binary64, no epsilon in ordering',
            'tie_break':'UTF-8 lexicographic fragment_id then doc_id',
            'query_time_fixed':'2026-11-17','norm_validation_tolerance':1e-12}
    write_json(out/'embedding_config.json',config)
    print(json.dumps(stats,ensure_ascii=False))

def embed(prepared,binary,model,selection):
    import numpy as np
    if sha(model)!='970aa74c0a90ef7482477cf803618e776e173c007bf957f635f1015bfcfef0e6':
        raise ValueError('Wrong model SHA256')
    target=prepared/('embeddings_'+selection)
    if target.exists():raise ValueError('Embedding output exists; do not overwrite.')
    target.mkdir()
    rows=[]
    for kind,file,prefix in [('fragment','fragments.jsonl','search_document: '),('query','queries.jsonl','search_query: ')]:
        for line in (prepared/file).read_text().splitlines():
            row=json.loads(line)
            if selection!='all' and row['split']!=selection:continue
            rows.append({'kind':kind,'id':row['fragment_id'] if kind=='fragment' else row['query_id'],
                         'split':row['split'],'text':prefix+(row['text'] if kind=='fragment' else row['query_text'])})
    inp=target/'input.txt';inp.write_text('\n'.join(r['text'] for r in rows)+'\n')
    env=os.environ.copy();env.update({'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','OLLAMA_NO_CLOUD':'1'})
    command=[str(binary),'--offline','-m',str(model),'-ngl','0','-t','4','-c','2048','-b','2048','-ub','2048',
             '--pooling','mean','--embd-normalize','2','--embd-output-format','json','-f',str(inp)]
    started=time.monotonic()
    with (target/'raw_embeddings.json').open('w') as stdout,(target/'stderr.txt').open('w') as stderr:
        cp=subprocess.run(command,stdout=stdout,stderr=stderr,env=env)
    elapsed=time.monotonic()-started
    write_json(target/'invocation.json',{'command':command,'binary_resolved':str(binary.resolve()),
                'binary_sha256':sha(binary),'exit_code':cp.returncode,'wall_seconds':elapsed,
                'purpose':'data preparation, not method performance comparison','network_used':False,
                'input_texts':len(rows),'input_sha256':sha(inp),'python':sys.version,'platform':platform.platform()})
    if cp.returncode:raise RuntimeError('Embedding runtime failed; inspect stored stderr.')
    result=json.loads((target/'raw_embeddings.json').read_text())
    data=result['data'];assert len(data)==len(rows),(len(data),len(rows))
    vectors=[]
    for i,item in enumerate(data):
        assert item['index']==i,(i,item['index'])
        v=[float(x) for x in item['embedding']]
        assert len(v)==768 and all(math.isfinite(x) for x in v)
        n=math.sqrt(math.fsum(x*x for x in v));assert n>0
        v=[x/n for x in v];assert abs(math.fsum(x*x for x in v)-1)<1e-12
        vectors.append(v)
    array=np.asarray(vectors,dtype=np.float64);np.save(target/'vectors.npy',array,allow_pickle=False)
    index=[{'row':i,'id':r['id'],'kind':r['kind'],'split':r['split'],'text_sha256':hashlib.sha256(r['text'].encode()).hexdigest(),'config_version':CONFIG} for i,r in enumerate(rows)]
    write_lines(target/'index.jsonl',index)
    write_json(target/'validation.json',{'passed':True,'vectors':len(rows),'dimension':768,
                'finite':True,'normalized':True,'max_abs_squared_norm_error':float(np.max(abs(np.sum(array*array,axis=1)-1))),
                'selection':selection,'performance_experiment':False,'semantic_relevance_validated':False,
                'vectors_sha256':sha(target/'vectors.npy'),'input_order_verified_by_runtime_indices':True})
    print(json.dumps({'embedding_validation':'passed','vectors':len(rows),'selection':selection,'seconds':round(elapsed,3)},ensure_ascii=False))

def main():
    ap=argparse.ArgumentParser();sub=ap.add_subparsers(dest='action',required=True)
    p=sub.add_parser('build');p.add_argument('--raw',type=Path,default=ROOT/'data/raw/onet_29_3');p.add_argument('--out',type=Path,required=True)
    p=sub.add_parser('embed');p.add_argument('--prepared',type=Path,required=True);p.add_argument('--selection',choices=['development','validation','final_holdout','all'],default='development')
    p.add_argument('--binary',type=Path,default=Path('/opt/homebrew/bin/llama-embedding'));p.add_argument('--model',type=Path,default=ROOT/'data/raw/models/nomic_embed_text/weights.gguf')
    a=ap.parse_args()
    if a.action=='build':build(a.raw,a.out)
    else:embed(a.prepared,a.binary,a.model,a.selection)

if __name__=='__main__':main()
