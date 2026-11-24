#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sequential frozen E07 execution, immutable runs and independent checks."""
import argparse,collections,json,os,random,subprocess,sys,time
from datetime import datetime
from zoneinfo import ZoneInfo
from e07_common import ROOT,sha,dump_new,cold_vectors,prepared_workload,expected_fast
A=ROOT/'reports/e_stages/E07/E07_2026-11-18_01';OUT=ROOT/'results/iterations/E07_2026-11-18_01'
LABELS={'C1_ORIGINAL':('pvldb_a','C1'),'C1_I01':('pvldb_a_e07_i01','C1'),'C1_NO_CERT_I01':('pvldb_a_e07_i01','C1_NO_CERT')}
for method in ['B0_FULL_EXACT','B1_DELTA_MATRIX','B2_RESERVE_EXACT','B2_ADAPTIVE','B3_ALL_SCORES','B4_SIMPFER_EXACT','B5_SIMPFERPP_EXACT','B6_HYBRID_EXACT']:LABELS[method+'_I01']=('pvldb_a_e07_i01',method)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--phase',required=True,choices=['headroom','I01','regressions']);args=ap.parse_args();phase=args.phase
    policy=json.loads((ROOT/'protocol/improvement_policy.json').read_text());manifest=json.loads((OUT/'workload_manifest.json').read_text())
    cases=manifest['cases'] if phase=='headroom' else ([c for c in manifest['cases'] if c['comparison_selected']] if phase=='I01' else manifest['ready_regressions'])
    blocks=policy['headroom']['measured_blocks'] if phase=='headroom' else (policy['comparison']['measured_blocks'] if phase=='I01' else policy['comparison']['ready_blocks'])
    if phase!='headroom':
        validation=json.loads((A/'I01_validation.json').read_text());assert validation['all_checks_passed']
    script_paths=[ROOT/'scripts/run_e07_case.py',ROOT/'scripts/execute_e07.py',ROOT/'scripts/e07_common.py']
    package_paths=list((ROOT/'src/pvldb_a').glob('*.py'))
    if phase!='headroom':package_paths+=list((ROOT/'src/pvldb_a_e07_i01').glob('*.py'))
    execution={'phase':phase,'policy_sha256':sha(ROOT/'protocol/improvement_policy.json'),'workload_manifest_sha256':sha(OUT/'workload_manifest.json'),
        'code_sha256':{str(p.relative_to(ROOT)):sha(p) for p in script_paths+package_paths},'started_at':datetime.now(ZoneInfo('Europe/Moscow')).isoformat(),
        'blocks':blocks,'E08_started':False}
    dump_new(A/('execution_'+phase+'_manifest.json'),execution)
    rng=random.Random(policy['comparison']['random_seed']+{'headroom':0,'I01':1,'regressions':2}[phase]);schedule=[]
    for b in range(blocks+1):
        jobs=[]
        for c in cases:
            if phase=='headroom':methods=['B3_HEADROOM']
            elif phase=='regressions':methods=policy['comparison']['ready_methods']
            else:methods=policy['comparison']['strong_panel']+(policy['comparison']['additional_panel'] if b<=policy['comparison']['additional_panel_measured_blocks'] else [])
            for method in methods:jobs.append((c,method))
        rng.shuffle(jobs)
        for c,m in jobs:schedule.append({'case_id':c['id'],'label':m,'block':b,'warmup':b==0})
    dump_new(A/('schedule_'+phase+'.json'),{'schedule':schedule,'seed':policy['comparison']['random_seed'],'E08_started':False})
    case_by={c['id']:c for c in cases};expected_cache={};digests={};records=[]
    for job in schedule:
        c=case_by[job['case_id']];label=job['label'];pkg,method=('pvldb_a','B3_ALL_SCORES') if phase=='headroom' else LABELS[label]
        run_id='E07_v1_'+phase+'_'+('warm' if job['warmup'] else 'b%02d'%job['block'])+'_'+c['id']+'_'+label
        out=OUT/'runs'/run_id;assert not out.exists() and sha(ROOT/c['path'])==c['sha256']
        cmd=[sys.executable,str(ROOT/'scripts/run_e07_case.py'),'--package',pkg,'--method',method,'--workload',str(ROOT/c['path']),'--out',str(out),
             '--timeout',str(policy['comparison']['common_timeout_seconds']),'--max-rss-bytes',str(policy['comparison']['common_max_rss_bytes'])]
        start=datetime.now(ZoneInfo('Europe/Moscow')).isoformat();load=os.getloadavg()
        therm=subprocess.run(['/usr/bin/pmset','-g','therm'],capture_output=True,text=True)
        result=subprocess.run(cmd,capture_output=True,text=True,cwd=ROOT)
        if not (out/'supervisor.json').exists():
            dump_new(A/(run_id+'_launch_failure.json'),{'command':cmd,'stdout':result.stdout,'stderr':result.stderr,'exit_code':result.returncode});raise RuntimeError('supervisor did not produce log')
        dump_new(out/'provenance.json',{'command':cmd,'package':pkg,'method':method,'phase':phase,'block':job['block'],'warmup':job['warmup'],
            'started_at':start,'background_load':load,'thermal_stdout':therm.stdout,'thermal_stderr':therm.stderr,
            'policy_sha256':execution['policy_sha256'],'workload_sha256':c['sha256'],'execution_manifest_sha256':sha(A/('execution_'+phase+'_manifest.json')),
            'supervisor_stdout':result.stdout,'supervisor_stderr':result.stderr,'exit_code':result.returncode,'E08_started':False})
        supervisor=json.loads((out/'supervisor.json').read_text());status=supervisor['status']
        row=dict(job,run_id=run_id,phase=phase,method=method,package=pkg,status=status,path=str(out.relative_to(ROOT)),supervisor_sha256=sha(out/'supervisor.json'))
        if status=='completed':
            w=json.loads((out/'worker.json').read_text());workload=json.loads((ROOT/c['path']).read_text())
            if w['mode']=='cold':
                cache,digest=cold_vectors(out);assert digest==w['embedding_vector_digest'];prepared=prepared_workload(workload,cache)
            else:digest='ready';prepared=workload
            if c['id'] in digests:assert digests[c['id']]==digest
            digests[c['id']]=digest
            key=(c['id'],digest);exp_path=OUT/'expected'/(c['id']+'_'+digest[:16]+'.json')
            if key not in expected_cache:
                if exp_path.exists():expected_cache[key]=json.loads(exp_path.read_text())
                else:
                    expected_cache[key]=expected_fast(prepared);dump_new(exp_path,expected_cache[key])
            expected=expected_cache[key];correct=w['outputs']==expected['outputs']
            dump_new(out/'validation.json',{'all_outputs_match':correct,'expected_path':str(exp_path.relative_to(ROOT)),'expected_sha256':sha(exp_path),
                'vector_digest':digest,'snapshots':len(w['outputs']),'query_outputs':sum(len(x) for x in w['outputs']),'external_validator_in_T_total':False})
            row.update(T_total_ns=w['T_total_ns'],worker_sha256=sha(out/'worker.json'),validation_sha256=sha(out/'validation.json'),correct=correct,
                snapshots=len(w['outputs']),query_outputs=sum(len(x) for x in w['outputs']),vector_digest=digest,
                operational_tree_upper_bytes=w['peak_tree_upper_bound_bytes'],sampled_whole_life_peak_bytes=supervisor['sampled_tree_peak_bytes'])
            if not correct:raise AssertionError(run_id+' full output mismatch')
        with (OUT/'runs.jsonl').open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
        records.append(row)
        print(json.dumps({'phase':phase,'progress':len(records),'planned':len(schedule),'block':job['block'],'case':c['id'],'method':label,'status':status,'seconds':row.get('T_total_ns',0)/1e9}),flush=True)
        if status not in ['completed','timeout','memory_limit']:raise RuntimeError(run_id+' unexpected failure; retained')
    dump_new(A/('execution_'+phase+'_complete.json'),{'phase':phase,'runs':len(records),'statuses':dict(collections.Counter(x['status'] for x in records)),
        'all_completed_outputs_correct':all(x.get('correct',True) for x in records),'digests':digests,'completed_at':datetime.now(ZoneInfo('Europe/Moscow')).isoformat(),'E08_started':False})
if __name__=='__main__':main()
