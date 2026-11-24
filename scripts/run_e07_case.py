#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Versioned E07 runner: same full worker path and actual per-query reads."""
import argparse,hashlib,importlib,json,os,resource,signal,subprocess,sys,time,traceback
from pathlib import Path
R=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def worker(a):
    start=time.perf_counter_ns()
    os.environ.update({k:'1' for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS']})
    sys.path.insert(0,str(R/'src'))
    Engine=importlib.import_module(a.package+'.engine').Engine
    answer=importlib.import_module(a.package+'.model').answer
    from pvldb_a.embedding import LocalEmbeddings
    from pvldb_a.metrics import Metrics
    runtime=time.perf_counter_ns();out=Path(a.out);metrics=Metrics();provider=None;outputs=[];engine_stats=[];read_latencies=[];read_groups=[]
    def read_all(engine):
        result={};latencies=[]
        # Each query is a separate pinned read including pin/release overhead.
        for qid in tuple(engine._root.queries):
            t=time.perf_counter_ns()
            with engine.pin() as reader:
                root=reader._root;value=answer(root.queries[qid],root.reserves[qid],root.version)
            latencies.append(time.perf_counter_ns()-t);result[qid]=value
        read_latencies.extend(latencies);read_groups.append(latencies);return result
    try:
        with metrics.span('lifecycle_total'):
            with metrics.span('input_preparation'):
                w=json.loads(Path(a.workload).read_text());assert w['split']=='development'
                docs=w['documents'];qs=w['queries'];mode=w['mode']
                if mode=='cold':provider=LocalEmbeddings(out/'embedding',timeout=a.timeout);docs,qs,_=provider.prepare(docs=docs,queries=qs)
                else:assert mode=='ready_vectors'
            params=dict(w.get('parameters',{}))
            if a.leaf_limit is not None:params['leaf_limit']=a.leaf_limit
            with metrics.span('initialization'):
                e=Engine(a.method,**params);e.build(docs,qs,w['corpus_version']);engine_stats.append(e.last_metrics)
            version=w['corpus_version']
            with metrics.span('scheduled_reads'):outputs.append(read_all(e))
            for batch in w['batches']:
                events=batch['events'];registry=batch.get('queries');rebuild=batch.get('documents')
                with metrics.span('delta_preparation'):
                    if provider:rebuild,registry,events=provider.prepare(docs=rebuild,queries=registry,events=events)
                with metrics.span('maintenance'):
                    e.apply(events,batch['corpus_version'],version,queries=registry,documents=rebuild,cap=batch.get('cap'))
                    engine_stats.append(e.last_metrics);version=batch['corpus_version']
                with metrics.span('scheduled_reads'):outputs.append(read_all(e))
            with metrics.span('response_serialization'):encoded=json.dumps(outputs,ensure_ascii=False,allow_nan=False)
        end=time.perf_counter_ns();own=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss;calls=provider.calls if provider else []
        result={'status':'completed','stage':'E07_DEVELOPMENT','package':a.package,'method':a.method,'parameters':params,'mode':mode,
            'T_total_ns':end-start,'timer_start_ns':start,'timer_end_ns':end,'metrics':metrics.report(),'engine_metrics':engine_stats,
            'outputs':outputs,'response_bytes':len(encoded.encode('utf8')),'read_latency_ns':read_latencies,'read_groups_ns':read_groups,
            'read_definition':'one query with pin/materialization/release; collect dict and timer instrumentation additionally charged in total',
            'embedding_calls':calls,'embedding_vector_digest':provider.vector_digest() if provider else None,
            'peak_self_rss_bytes':own,'peak_tree_upper_bound_bytes':own+max((x['peak_child_rss_bytes'] for x in calls),default=0),
            'runtime_import_and_thread_setup_ns':runtime-start,'runtime_setup_in_T_total':True,
            'validator_in_T_total':False,'report_generation_in_T_total':False,'source_preparation_in_T_total':True,
            'source_hashes':{str(p.relative_to(R)):sha(p) for p in list((R/'src'/a.package).glob('*.py'))+[Path(__file__).resolve(),R/'src/pvldb_a/embedding.py']},
            'E08_started':False}
        (out/'worker.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    except BaseException:
        (out/'worker_failure.json').write_text(json.dumps({'status':'failed','error':traceback.format_exc(),'metrics':metrics.report(),'E08_started':False},indent=2));raise

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--package',default='pvldb_a');ap.add_argument('--method',required=True);ap.add_argument('--workload',required=True);ap.add_argument('--out',required=True)
    ap.add_argument('--timeout',type=float,default=45);ap.add_argument('--max-rss-bytes',type=int,default=16*1024**3);ap.add_argument('--leaf-limit',type=int);ap.add_argument('--worker',action='store_true');a=ap.parse_args()
    if a.worker:return worker(a)
    out=Path(a.out);out.mkdir(parents=True,exist_ok=False)
    cmd=[sys.executable,str(Path(__file__).resolve()),'--worker','--package',a.package,'--method',a.method,'--workload',str(Path(a.workload).resolve()),'--out',str(out.resolve()),'--timeout',str(a.timeout),'--max-rss-bytes',str(a.max_rss_bytes)]
    if a.leaf_limit is not None:cmd+=['--leaf-limit',str(a.leaf_limit)]
    from run_pilot import tree_rss
    samples=[];reason=None;start=time.monotonic();env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OLLAMA_NO_CLOUD='1')
    with (out/'stdout.txt').open('x') as stdout,(out/'stderr.txt').open('x') as stderr:
        child=subprocess.Popen(cmd,stdout=stdout,stderr=stderr,env=env,start_new_session=True,cwd=R)
        while child.poll() is None:
            rss,n=tree_rss(child.pid);elapsed=time.monotonic()-start;samples.append({'elapsed_seconds':elapsed,'tree_rss_bytes':rss,'processes':n})
            if elapsed>a.timeout:reason='timeout'
            elif rss>a.max_rss_bytes:reason='memory_limit'
            if reason:os.killpg(child.pid,signal.SIGKILL);break
            time.sleep(.01)
        code=child.wait()
    result={'stage':'E07_DEVELOPMENT','package':a.package,'method':a.method,'status':reason or ('completed' if code==0 else 'failed'),
        'exit_code':code,'command':cmd,'timeout_seconds':a.timeout,'max_rss_bytes':a.max_rss_bytes,'samples':samples,
        'sampled_tree_peak_bytes':max((x['tree_rss_bytes'] for x in samples),default=0),'memory_scope':'sampled whole process life, distinct from operational self+child upper','network_used':False,'E08_started':False}
    (out/'supervisor.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'status':result['status'],'method':a.method,'package':a.package}))
    if code or reason:raise SystemExit(1)
if __name__=='__main__':main()
