#!/usr/bin/env python3
"""Sequential E05 execution only; old E04 kernel/runner remain unchanged."""
import copy, datetime, hashlib, json, os, random, subprocess, sys, time, traceback
from pathlib import Path
os.environ.update({k: '1' for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','VECLIB_MAXIMUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']})
from e05_common import ROOT, dump_new, sha, expected_trace, cold_vectors, prepared_workload
from e05_statistics import precision
ATTEMPT = ROOT / 'reports/e_stages/E05/E05_2026-11-18_01'
BASE = ROOT / 'results/pilot/E05_2026-11-18_01'
PYTHON = '/Library/Developer/CommandLineTools/usr/bin/python3'

def background():
    ps = subprocess.run(['/bin/ps','-axo','pid=,pcpu=,comm='],capture_output=True,text=True)
    rows = []
    for line in ps.stdout.splitlines():
        fields = line.split(None,2)
        if len(fields) == 3:
            try: rows.append({'pid':int(fields[0]),'cpu_percent':float(fields[1]),'process_name':Path(fields[2]).name})
            except ValueError: pass
    rows.sort(key=lambda x:-x['cpu_percent'])
    thermal = subprocess.run(['/usr/bin/pmset','-g','therm'],capture_output=True,text=True)
    return {'load_average':list(os.getloadavg()), 'top_cpu_process_names':rows[:8],
            'thermal_exit_code':thermal.returncode,'thermal_stdout':thermal.stdout,'thermal_stderr':thermal.stderr}

def main():
    protocol = json.loads((ROOT / 'protocol/pilot_v1.json').read_text()); ph = sha(ROOT / 'protocol/pilot_v1.json')
    for f,h in protocol['input_sha256'].items(): assert sha(ROOT / f)==h,(f,'changed frozen input')
    for c in protocol['cases']: assert sha(ROOT / c['path'])==c['sha256']
    implementation = json.loads((ROOT / 'validation/implementation_report.json').read_text())
    frozen_sources = dict(implementation['source_hashes']); frozen_sources['scripts/run_pilot.py'] = sha(ROOT / 'scripts/run_pilot.py')
    for f,h in frozen_sources.items(): assert sha(ROOT / f)==h
    files = ['scripts/execute_e05_pilot.py','scripts/e05_statistics.py','scripts/e05_common.py','scripts/prepare_e05_pilot.py']
    dump_new(ATTEMPT / 'execution_manifest.json', {'version':'A-E05-execution-1.0','protocol_sha256':ph,
        'code_sha256':{f:sha(ROOT / f) for f in files},'implementation_sha256':frozen_sources,
        'python':PYTHON,'E06_started':False,'started_at':datetime.datetime.now().astimezone().isoformat()})
    records=[]; expected_cache={}; seen_cold={}; run_count=0
    index = (ROOT / 'results/pilot_runs.jsonl').open('x')

    def execute(case, method, block, phase):
        nonlocal run_count
        run_id = 'E05_v1_' + phase + '_b%02d_' % block + case['id'] + '_' + method
        out = BASE / 'runs' / run_id
        cmd = [PYTHON,str(ROOT/'scripts/run_pilot.py'),'--stage','E05_PILOT','--method',method,
               '--workload',str(ROOT/case['path']),'--out',str(out),'--timeout',str(case['timeout_seconds']),
               '--max-rss-bytes',str(case['max_rss_bytes'])]
        before = background(); start = datetime.datetime.now().astimezone().isoformat(); wall = time.monotonic()
        process = subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=case['timeout_seconds']+60)
        (out/'launcher_stdout.txt').write_text(process.stdout); (out/'launcher_stderr.txt').write_text(process.stderr)
        sup=json.loads((out/'supervisor.json').read_text()); status=sup['status']
        provenance={'run_id':run_id,'phase':phase,'block':block,'case_id':case['id'],'method':method,
            'protocol_sha256':ph,'workload_sha256':case['sha256'],'command':cmd,'started_at':start,
            'launcher_wall_seconds':time.monotonic()-wall,'launcher_returncode':process.returncode,
            'background_before':before,'E06_started':False}
        dump_new(out/'provenance.json',provenance)
        row={k:provenance[k] for k in ['run_id','phase','block','case_id','method','protocol_sha256','workload_sha256','started_at']}
        row.update(status=status,role=case['role'],mode=case['mode'],path=str(out.relative_to(ROOT)),
                   supervisor_sha256=sha(out/'supervisor.json'),sampled_tree_peak_bytes=sup['sampled_tree_peak_bytes'])
        if status=='completed':
            worker=json.loads((out/'worker.json').read_text()); workload=json.loads((ROOT/case['path']).read_text())
            for f,h in worker['source_hashes'].items(): assert frozen_sources[f]==h,('source_changed',f)
            if case['mode']=='cold':
                cache,digest=cold_vectors(out); assert digest==worker['embedding_vector_digest']
                key=(case['id'],digest); prepared=prepared_workload(workload,cache)
                if case['id'] in seen_cold and seen_cold[case['id']]!=digest:
                    dump_new(out/'input_repeatability_failure.json',{'previous_digest':seen_cold[case['id']],'current_digest':digest})
                    raise AssertionError(('cold_numeric_input_not_repeatable',run_id))
                seen_cold[case['id']]=digest
            else: key=(case['id'],'ready'); prepared=workload; digest=None
            if key not in expected_cache:
                answers,trace=expected_trace(prepared)
                ep=BASE/'expected'/(case['id']+'_'+key[1]+'.json')
                dump_new(ep,{'case_id':case['id'],'vector_digest':digest,'outputs':answers,'trace':trace,
                             'independent_oracle_sha256':sha(ROOT/'src/pvldb_a/oracle.py'),'validator_sha256':sha(ROOT/'scripts/e05_common.py')})
                expected_cache[key]=(answers,ep)
            expected,ep=expected_cache[key]; matched=worker['outputs']==expected
            validation={'all_outputs_match':matched,'snapshots':len(expected),'query_outputs':sum(len(x) for x in expected),
                        'expected_path':str(ep.relative_to(ROOT)),'expected_sha256':sha(ep),'vector_digest':digest,
                        'validator_excluded_from_T_total':True,'complete_versions_and_order':True}
            dump_new(out/'validation.json',validation)
            if not matched:
                dump_new(out/'mismatch.json',{'expected':expected,'actual':worker['outputs']})
                status='output_mismatch';row['status']=status
            row.update(T_total_ns=worker['T_total_ns'],peak_tree_upper_bound_bytes=worker['peak_tree_upper_bound_bytes'],
                       validation_sha256=sha(out/'validation.json'),worker_sha256=sha(out/'worker.json'),
                       correct=matched,query_outputs=validation['query_outputs'],snapshots=validation['snapshots'],
                       vector_digest=digest,embedding_calls=len(worker['embedding_calls']))
        records.append(row);index.write(json.dumps(row,ensure_ascii=False)+'\n');index.flush();os.fsync(index.fileno());run_count+=1
        if status in ('failed','output_mismatch'):
            raise RuntimeError(('implementation_or_runner_failure',run_id,status))
        if run_count%10==0: print(json.dumps({'runs':run_count,'last':run_id,'status':status}),flush=True)

    def run_block(block, phase, cases):
        rng=random.Random(18051801+block+(100000 if phase=='warmup' else 0));ordered=list(cases);rng.shuffle(ordered)
        for case in ordered:
            methods=list(case['methods']);rng.shuffle(methods)
            for method in methods:execute(case,method,block,phase)
        print(json.dumps({'block_complete':block,'phase':phase,'runs':run_count}),flush=True)

    try:
        run_block(0,'warmup',protocol['cases'])
        for block in range(1,21):
            run_block(block,'measured',[c for c in protocol['cases'] if c['timing_blocks']>=block])
        decision=precision(records,protocol,20);dump_new(ATTEMPT/'precision_at_20.json',decision)
        print(json.dumps({'precision_at_20_met':decision['all_primary_precision_met'],'extend':decision['extend_by_preregistered_rule']}),flush=True)
        last=20
        if decision['extend_by_preregistered_rule']:
            for block in range(21,41):run_block(block,'measured',[c for c in protocol['cases'] if c['role']!='diagnostic_memory_limit'])
            last=40
        final=precision(records,protocol,last);dump_new(ATTEMPT/'precision_final.json',final)
        dump_new(ATTEMPT/'execution_complete.json',{'status':'completed','runs':run_count,'measured_runs':sum(r['phase']=='measured' for r in records),
            'final_blocks':last,'cold_digests':seen_cold,'all_completed_outputs_correct':all(r.get('correct',True) for r in records),
            'E06_started':False,'completed_at':datetime.datetime.now().astimezone().isoformat()})
    except BaseException:
        dump_new(ATTEMPT/'execution_failure.json',{'status':'failed','runs_recorded':run_count,'traceback':traceback.format_exc(),'E06_started':False})
        raise
    finally:index.close()

if __name__=='__main__':main()
