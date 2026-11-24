"""Sequential predeclared development runs; exact independent answer verification."""
import collections,copy,datetime,gzip,hashlib,json,math,os,struct,subprocess,sys,time
from pathlib import Path
from e05_common import ROOT,sha,dump_new,replay_events
from pvldb_a.oracle import exact

A=ROOT/'reports/exploration/EX01_2026-11-18_01'
D=ROOT/'data/derived/EX01_2026-11-18_01'
R=ROOT/'results/exploration/EX01_2026-11-18_01'

def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def expected(w):
    # Full scan for each snapshot; scalar score cache keyed only by immutable vectors.
    # No production model/scorer, partition, pruning or certificate imports.
    vector_ids={};vectors={};scores={};record_ids={};query_ids={}
    def vector_id(v):
        bits=struct.pack('='+str(len(v))+'d',*v)
        if bits not in vector_ids:
            assert len(v)==768 and all(math.isfinite(x) for x in v) and abs(math.fsum(x*x for x in v)-1)<1e-12
            i=len(vectors);vector_ids[bits]=i;vectors[i]=tuple(v)
        return vector_ids[bits]
    def reg(d):
        for f in d['fragments']:
            key=d['doc_id'],f['fragment_id'],f['text_version'];v=vector_id(f['vector']);sig=(v,f['text'])
            if key in record_ids:assert record_ids[key]==sig
            record_ids[key]=sig
    for d in w['documents']:reg(d)
    for b in w['batches']:
        for e in b['events']:
            if e['op']=='put_document':reg(e['document'])
            elif e['op']=='put_fragment':reg({'doc_id':e['doc_id'],'fragments':[e['fragment']]})
    for q in w['queries']:query_ids[q['query_id']]=vector_id(q['vector'])
    def snap(ds,version):
        out={}
        for q in w['queries']:
            rows=[];qi=query_ids[q['query_id']]
            for d in ds:
                md=d['metadata']
                if md.get('enabled') is not True or not md.get('valid_from','9999')<=q['query_time']<md.get('valid_to','0000'):continue
                if any(k not in md or md[k]!=v for k,v in q['filter'].items()):continue
                frags=[]
                for f in d['fragments']:
                    vi=record_ids[d['doc_id'],f['fragment_id'],f['text_version']][0];key=qi,vi
                    if key not in scores:scores[key]=math.fsum(x*y for x,y in zip(vectors[qi],vectors[vi]))
                    frags.append((scores[key],f))
                if frags:
                    score,f=min(frags,key=lambda z:(-z[0],z[1]['fragment_id'].encode('utf8')))
                    rows.append((score,d['doc_id'],f['fragment_id'],f['text_version']))
            rows.sort(key=lambda x:(-x[0],x[1].encode('utf8')))
            out[q['query_id']]={'query_id':q['query_id'],'query_version':q['query_version'],'config_version':q['config_version'],
                'corpus_version':version,'ordered_hits':[[did,fid,v] for _,did,fid,v in rows[:q['k']]]}
        return out
    ds=copy.deepcopy(w['documents']);outs=[snap(ds,w['corpus_version'])];crosschecks=0
    for q in w['queries']:
        assert outs[0][q['query_id']]==exact(ds,q,w['corpus_version']);crosschecks+=1
    for i,b in enumerate(w['batches']):
        ds=replay_events(ds,b['events']);out=snap(ds,b['corpus_version']);outs.append(out)
        if i in [len(w['batches'])//2-1,len(w['batches'])-1]:
            q=w['queries'][0];assert out[q['query_id']]==exact(ds,q,b['corpus_version']);crosschecks+=1
    return {'answer_sha256':digest(outs),'snapshots':len(outs),'answers':sum(len(o) for o in outs),
            'scalar_scores':len(scores),'uncached_reference_crosschecks':crosschecks,
            'oracle':'Full snapshot scan, pure Python math.fsum, immutable-vector memoization; independent of engine pruning',
            'outputs':outs}

def main():
    R.mkdir(parents=True,exist_ok=True)
    assert not (R/'oracle').exists() and not (R/'runs').exists(), 'Do not overwrite an executed attempt'
    manifest=json.loads((D/'manifest.json').read_text());schedule=json.loads((A/'schedule.json').read_text())
    assert schedule['policy_sha256']==sha(A/'policy.json') and schedule['data_manifest_sha256']==sha(D/'manifest.json')
    for p,h in manifest['source_hashes'].items():assert sha(ROOT/p)==h
    reference={}
    for c in manifest['cases']:
        assert sha(ROOT/c['path'])==c['sha256']
        w=json.loads((ROOT/c['path']).read_text());result=expected(w)
        target=R/'oracle'/f'{c["id"]}.json.gz';target.parent.mkdir(exist_ok=True)
        with gzip.open(target,'wt',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,separators=(',',':'))
        reference[c['id']]={k:v for k,v in result.items() if k!='outputs'}
        print(json.dumps({'oracle_ready':c['id'],'answers':result['answers']}),flush=True)
    dump_new(A/'oracle_manifest.json',reference)
    engine_files=list((ROOT/'src/pvldb_a_e07_i01').glob('*.py'))+list((ROOT/'src/pvldb_a').glob('*.py'))
    dump_new(A/'execution_manifest.json',{'schedule_sha256':sha(A/'schedule.json'),'data_manifest_sha256':sha(D/'manifest.json'),
        'code_sha256':{str(p.relative_to(ROOT)):sha(p) for p in engine_files+[Path(__file__).resolve(),ROOT/'scripts/run_ex01_case.py']},
        'started_at':datetime.datetime.now().astimezone().isoformat(),'network_used':False,'new_E03_started':False})
    for n,run in enumerate(schedule['runs']):
        out=R/'runs'/run['run_id']
        command=[sys.executable,'scripts/run_ex01_case.py','--package',run['package'],'--method',run['method'],
                 '--workload',str(ROOT/run['workload']),'--out',str(out),'--timeout','60','--max-rss-bytes',str(16*1024**3)]
        started=time.time();p=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
        supervisor=json.loads((out/'supervisor.json').read_text())
        status=supervisor['status'];validation={'status':'not_available','mismatches':None}
        summary={**run,'status':status,'exit_code':p.returncode,'run_dir':str(out.relative_to(ROOT)),
                 'wall_seconds_including_post_timing_output':time.time()-started,'T_total_ns':None}
        if status=='completed':
            with gzip.open(out/'worker.json.gz','rt',encoding='utf-8') as f:worker=json.load(f)
            observed=digest(worker['outputs']);ref=reference[run['case_id']]
            validation={'status':'passed' if observed==ref['answer_sha256'] else 'failed',
                        'mismatches':0 if observed==ref['answer_sha256'] else 'nonzero',
                        'actual_answer_sha256':observed,'expected_answer_sha256':ref['answer_sha256'],'answers':ref['answers']}
            summary.update(T_total_ns=worker['T_total_ns'],validation=validation['status'],answers=ref['answers'],
                score_pairs=sum(x['counts'].get('score_pairs',0) for x in worker['engine_metrics']),
                certified_cells=sum(x['counts'].get('certified_cells',0) for x in worker['engine_metrics']),
                bound_pairs=sum(x['counts'].get('bound_pairs',0) for x in worker['engine_metrics']),
                rss_operational_upper=worker['peak_tree_upper_bound_bytes'])
        dump_new(out/'validation.json',validation)
        with (A/'runs.jsonl').open('a') as f:f.write(json.dumps(summary,ensure_ascii=False)+'\n')
        print(json.dumps({'progress':n+1,'total':len(schedule['runs']),'case':run['case_id'],'method':run['method'],
                          'phase':run['phase'],'status':status,'T_seconds':None if summary['T_total_ns'] is None else summary['T_total_ns']/1e9,
                          'validation':validation['status']}),flush=True)
        if validation['status']=='failed':
            dump_new(A/'halt.json',{'reason':'correctness failure','run_id':run['run_id'],'remaining_runs':'not_executed_not_removed'})
            raise RuntimeError('Answer mismatch; implementation exploration stopped')
    dump_new(A/'execution_complete.json',{'runs':len(schedule['runs']),'finished_at':datetime.datetime.now().astimezone().isoformat(),
             'new_E03_started':False,'E08_started':False,'physical_embeddings_executed':False,'scope':'exploratory ready-vector screen'})

if __name__=='__main__':main()
