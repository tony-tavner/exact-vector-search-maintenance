#!/usr/bin/env python3
"""Local lifecycle runner. E04_SMOKE validates infrastructure; E05_PILOT is explicit.
No scientific workload is generated or executed by importing this module.
"""
import argparse,hashlib,json,os,signal,subprocess,sys,time,traceback,resource
from pathlib import Path
R=Path(__file__).resolve().parents[1]
def worker(a):
    start=time.perf_counter_ns()
    # Thread limits precede NumPy/native imports and are common to every method.
    os.environ.update({k:'1' for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS']})
    sys.path.insert(0,str(R/'src'))
    if a.test_failure=='timeout':time.sleep(10)
    if a.test_failure=='memory_limit':blob=bytearray(256*1024*1024);time.sleep(10)
    if a.test_failure=='crash':raise RuntimeError('injected_infrastructure_failure')
    from pvldb_a.engine import Engine
    from pvldb_a.embedding import LocalEmbeddings
    from pvldb_a.metrics import Metrics
    out=Path(a.out);metrics=Metrics();provider=None;calls=[];engine_stats=[];outputs=[]
    runtime_ready_ns=time.perf_counter_ns()
    try:
        with metrics.span('lifecycle_total'):
            with metrics.span('input_preparation'):
                workload=json.loads(Path(a.workload).read_text())
                if workload.get('split') not in ('synthetic','development','validation'):raise ValueError('final_holdout_requires_separate_frozen_runner')
                docs=workload['documents'];qs=workload['queries'];mode=workload['mode']
                if mode=='cold':
                    provider=LocalEmbeddings(out/'embedding',timeout=a.timeout)
                    docs,qs,_=provider.prepare(docs=docs,queries=qs)
                elif mode!='ready_vectors':raise ValueError('unknown_vector_mode')
            with metrics.span('initialization'):
                engine=Engine(a.method,**workload.get('parameters',{}));engine.build(docs,qs,workload['corpus_version']);engine_stats.append(engine.last_metrics)
            version=workload['corpus_version']
            with metrics.span('scheduled_reads'):outputs.append(engine.answers())
            for batch in workload['batches']:
                events=batch['events'];registry=batch.get('queries');rebuild=batch.get('documents')
                with metrics.span('delta_preparation'):
                    if provider:rebuild,registry,events=provider.prepare(docs=rebuild,queries=registry,events=events)
                with metrics.span('maintenance'):
                    engine.apply(events,batch['corpus_version'],version,queries=registry,documents=rebuild,cap=batch.get('cap'))
                    engine_stats.append(engine.last_metrics);version=batch['corpus_version']
                with metrics.span('scheduled_reads'):outputs.append(engine.answers())
            with metrics.span('response_serialization'):encoded=json.dumps(outputs,ensure_ascii=False,allow_nan=False)
        end=time.perf_counter_ns()
        own=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        calls=provider.calls if provider else []
        result={'status':'completed','stage':a.stage,'method':a.method,'mode':mode,'T_total_ns':end-start,
                'timer_start_ns':start,'timer_end_ns':end,'metrics':metrics.report(),'engine_metrics':engine_stats,
                'outputs':outputs,'response_bytes':len(encoded.encode('utf8')),'embedding_calls':calls,
                'peak_self_rss_bytes':own,'peak_tree_upper_bound_bytes':own+max((c['peak_child_rss_bytes'] for c in calls),default=0),
                'tree_upper_bound_basis':'self high-water mark + maximum one sequential embedding child high-water mark; not an exact simultaneous peak',
                'source_preparation_in_T_total':True,'report_generation_in_T_total':False,'validator_in_T_total':False,
                'comparison_or_superiority_claim':False,'E05_started':a.stage=='E05_PILOT'}
        result['embedding_vector_digest']=provider.vector_digest() if provider else None
        result['runtime_import_and_thread_setup_ns']=runtime_ready_ns-start
        result['runtime_setup_in_T_total']=True
        result['source_hashes']={str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in list((R/'src/pvldb_a').glob('*.py'))+[Path(__file__).resolve()]}
        (out/'worker.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    except BaseException:
        failure={'status':'failed','error':traceback.format_exc(),'metrics':metrics.report(),'embedding_calls':provider.calls if provider else [],'E05_started':a.stage=='E05_PILOT'}
        (out/'worker_failure.json').write_text(json.dumps(failure,ensure_ascii=False,indent=2)+'\n');raise

def tree_rss(pid):
    text=subprocess.check_output(['/bin/ps','-axo','pid=,ppid=,rss='],text=True)
    rows=[tuple(map(int,line.split())) for line in text.splitlines() if len(line.split())==3]
    wanted={pid}
    while True:
        after=wanted|{p for p,pp,r in rows if pp in wanted}
        if after==wanted:break
        wanted=after
    return sum(r*1024 for p,pp,r in rows if p in wanted),len([p for p,pp,r in rows if p in wanted])

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--stage',required=True,choices=['E04_SMOKE','E05_PILOT'])
    ap.add_argument('--method',default='C1');ap.add_argument('--workload',required=True);ap.add_argument('--out',required=True)
    ap.add_argument('--timeout',type=float,default=120);ap.add_argument('--max-rss-bytes',type=int,default=16*1024**3)
    ap.add_argument('--test-failure',choices=['timeout','memory_limit','crash']);ap.add_argument('--worker',action='store_true')
    a=ap.parse_args()
    if a.test_failure and a.stage!='E04_SMOKE':ap.error('Failure injections only for E04 infrastructure tests')
    if a.timeout<=0 or a.max_rss_bytes<=0:ap.error('Positive resource limits required')
    if a.worker:return worker(a)
    out=Path(a.out);out.mkdir(parents=True,exist_ok=False)
    cmd=[sys.executable,str(Path(__file__).resolve()),'--worker','--stage',a.stage,'--method',a.method,'--workload',str(Path(a.workload).resolve()),
         '--out',str(out.resolve()),'--timeout',str(a.timeout),'--max-rss-bytes',str(a.max_rss_bytes)]
    if a.test_failure:cmd+=['--test-failure',a.test_failure]
    env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OLLAMA_NO_CLOUD='1')
    samples=[];reason=None;start=time.monotonic()
    with (out/'stdout.txt').open('w') as stdout,(out/'stderr.txt').open('w') as stderr:
        child=subprocess.Popen(cmd,stdout=stdout,stderr=stderr,env=env,start_new_session=True,cwd=R)
        while child.poll() is None:
            rss,count=tree_rss(child.pid);elapsed=time.monotonic()-start
            samples.append({'elapsed_seconds':elapsed,'tree_rss_bytes':rss,'processes':count})
            if elapsed>a.timeout:reason='timeout'
            elif rss>a.max_rss_bytes:reason='memory_limit'
            if reason:os.killpg(child.pid,signal.SIGKILL);break
            time.sleep(.01)
        code=child.wait()
    result={'stage':a.stage,'method':a.method,'status':reason or ('completed' if code==0 else 'failed'),
        'exit_code':code,'command':cmd,'timeout_seconds':a.timeout,'max_rss_bytes':a.max_rss_bytes,
        'samples':samples,'sampled_tree_peak_bytes':max((s['tree_rss_bytes'] for s in samples),default=0),
        'sampled_peak_is_lower_bound':True,'supervision_time_excluded_from_worker_T_total':True,
        'E05_started':a.stage=='E05_PILOT','network_used':False}
    (out/'supervisor.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ['stage','method','status','exit_code','sampled_tree_peak_bytes']}))
    if code!=0 or reason:raise SystemExit(1)
if __name__=='__main__':main()
