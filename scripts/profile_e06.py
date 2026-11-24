#!/usr/bin/env python3
"""Separate diagnostic call wrappers; canonical guards stay enabled, no tuning."""
import argparse, collections, functools, json, os, subprocess, sys, time
from pathlib import Path
from e05_common import ROOT, sha, dump_new

A = ROOT/'reports/e_stages/E06/E06_2026-11-18_01'
OUT = ROOT/'results/comparison/E06_2026-11-18_01'


def worker(case_id, method, output):
    os.environ.update({k:'1' for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS']})
    sys.path.insert(0,str(ROOT/'src'))
    from pvldb_a import engine as en, numeric as nu, blocks as bl
    case=next(c for c in json.loads((ROOT/'protocol/pilot_v1.json').read_text())['cases'] if c['id']==case_id)
    w=json.loads((ROOT/case['path']).read_text()); assert w['mode']=='ready_vectors' and w['split']=='development'
    events=[]; phase=['build']; covers=[]
    def instrument(name, fn):
        @functools.wraps(fn)
        def wrapped(*args,**kwargs):
            start=time.perf_counter_ns(); result=fn(*args,**kwargs);end=time.perf_counter_ns()
            record={'name':name,'phase':phase[0],'elapsed_ns':end-start}
            if name=='bounds':
                record.update(dimension=len(args[0]),query_box_width_nonzero=sum(lo!=hi for lo,hi in args[0]),result='unknown' if result is None else ('negative' if result<0 else 'nonnegative'))
            elif name=='matrix':record.update(queries=len(args[1]),fragments=len(args[2]),pairs=len(args[1])*len(args[2]))
            events.append(record);return result
        return wrapped
    wrapped_bounds=instrument('bounds',nu.bounds);nu.bounds=wrapped_bounds;en.bounds=wrapped_bounds
    wrapped_norm=instrument('norm2',nu.norm2);nu.norm2=wrapped_norm;en.norm2=wrapped_norm;bl.norm2=wrapped_norm
    en.norm_upper=instrument('norm_upper',en.norm_upper)
    nu.NumericContext.matrix=instrument('matrix',nu.NumericContext.matrix)
    original_cover=en.Engine._cover
    @functools.wraps(original_cover)
    def cover(self,old,new,block,m,cache=None,oldroot=None):
        # Reason classification is outside the timed original call and changes no inputs.
        reason='bound_attempt'; delta_count=None
        if old is None or new is None:reason='absent_old_or_new_document'
        elif old.metadata!=new.metadata:reason='metadata_changed'
        else:
            a={f.fid:f for f in old.fragments};b={f.fid:f for f in new.fragments}
            common={k for k in a if k in b and a[k].text is not None and a[k].identity==b[k].identity}
            if not common:reason='no_unchanged_witness'
            else:
                delta_count=sum(f.fid not in common for f in old.fragments)+sum(f.fid not in common for f in new.fragments)
                if not delta_count:reason='identical_fragment_records'
        before=m.counts.get('bound_pairs',0);start=time.perf_counter_ns()
        result=original_cover(self,old,new,block,m,cache,oldroot)
        elapsed=time.perf_counter_ns()-start
        covers.append({'phase':phase[0],'document_id':old.did if old else new.did,'members':len(block.members),
                       'reason':reason,'delta_fragments_two_sided':delta_count,'certified':result,
                       'bound_calls':m.counts.get('bound_pairs',0)-before,'elapsed_ns':elapsed})
        return result
    en.Engine._cover=cover
    assert sys.getprofile() is None and sys.gettrace() is None
    engine=en.Engine(method,**w.get('parameters',{}));metrics=[];outputs=[]
    engine.build(w['documents'],w['queries'],w['corpus_version']);metrics.append(engine.last_metrics);outputs.append(engine.answers())
    blocks=[{'id':b.bid,'members':len(b.members)} for b in engine._root.blocks]
    short=[len(engine._root.small)];version=w['corpus_version']
    for i,b in enumerate(w['batches']):
        phase[0]='update_%02d'%(i+1)
        engine.apply(b['events'],b['corpus_version'],version,queries=b.get('queries'),documents=b.get('documents'),cap=b.get('cap'))
        version=b['corpus_version'];metrics.append(engine.last_metrics);outputs.append(engine.answers());short.append(len(engine._root.small))
    assert sys.getprofile() is None and sys.gettrace() is None and engine.ctx.bound
    engine.check_invariants()
    prior=next(json.loads(x) for x in (ROOT/'results/pilot_runs.jsonl').read_text().splitlines()
               if json.loads(x)['case_id']==case_id and json.loads(x)['method']==method and json.loads(x)['status']=='completed')
    validation=json.loads((ROOT/prior['path']/'validation.json').read_text())
    expected=json.loads((ROOT/validation['expected_path']).read_text());assert outputs==expected['outputs']
    dump_new(Path(output),{'stage':'E06_DIAGNOSTIC_PROFILE','case_id':case_id,'method':method,
        'source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in (ROOT/'src/pvldb_a').glob('*') if p.is_file()},
        'workload_sha256':sha(ROOT/case['path']),'events':events,'coverage':covers,'blocks':blocks,
        'short_registry_counts':short,'engine_metrics':metrics,'outputs':outputs,
        'expected_path':validation['expected_path'],'expected_sha256':sha(ROOT/validation['expected_path']),
        'full_outputs_match':True,'numeric_guards_enabled':True,'sys_profile_and_trace_disabled':True,
        'interpretation':'Call-wrapper diagnostic, perturbed timing; nested calls overlap, never sum them into lifecycle. No performance claim or modification to the method.',
        'performance_series':False,'E07_started':False})


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--worker',action='store_true');ap.add_argument('--case');ap.add_argument('--method');ap.add_argument('--output');args=ap.parse_args()
    if args.worker:return worker(args.case,args.method,args.output)
    protocol=json.loads((A/'diagnostic_protocol.json').read_text());assert sha(Path(__file__))==protocol['profile_script_sha256']
    records=[]
    for job in protocol['profile_jobs']:
        dest=OUT/'profiles'/job['run_id'];dest.mkdir(parents=True,exist_ok=False)
        cmd=[sys.executable,str(Path(__file__).resolve()),'--worker','--case',job['case_id'],'--method',job['method'],'--output',str(dest/'profile.json')]
        start=time.monotonic();status='completed'
        with (dest/'stdout.txt').open('x') as out,(dest/'stderr.txt').open('x') as err:
            try:result=subprocess.run(cmd,stdout=out,stderr=err,timeout=protocol['profile_timeout_seconds'],cwd=ROOT);code=result.returncode;status='completed' if code==0 else 'failed'
            except subprocess.TimeoutExpired:status='timeout';code=None
        record=dict(job,status=status,exit_code=code,command=cmd,elapsed_diagnostic_seconds=time.monotonic()-start,profile_sha256=sha(dest/'profile.json') if (dest/'profile.json').exists() else None)
        dump_new(dest/'provenance.json',record);records.append(record)
        print(json.dumps({'profile':job['run_id'],'status':status}),flush=True)
        if status!='completed':break
    dump_new(OUT/'profile_index.json',{'records':records,'all_completed':len(records)==len(protocol['profile_jobs']) and all(r['status']=='completed' for r in records),'not_scientific_timing_repeats':True,'E07_started':False})


if __name__=='__main__':main()
