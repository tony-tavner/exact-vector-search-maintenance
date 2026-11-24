from pathlib import Path
import json,subprocess,sys,traceback
R=Path(__file__).resolve().parents[2];A=R/'reports/e_stages/E04/E04_2026-11-18_01'
def main():
    out=A/'infrastructure_validation_01.json';assert not out.exists();results=[]
    try:
        for name,workload,failure,timeout,limit in [
            ('ready_02','infrastructure_workload.json',None,60,2**30),
            ('cold_01','cold_infrastructure_workload.json',None,60,2**30),
            ('cold_02','cold_infrastructure_workload.json',None,60,2**30),
            ('timeout_01','infrastructure_workload.json','timeout',.2,2**30),
            ('memory_01','infrastructure_workload.json','memory_limit',10,64*2**20),
            ('crash_01','infrastructure_workload.json','crash',10,2**30)]:
            d=A/('infrastructure_'+name)
            cmd=[sys.executable,str(R/'scripts/run_pilot.py'),'--stage','E04_SMOKE','--method','C1','--workload',str(R/'tests/e04'/workload),'--out',str(d),'--timeout',str(timeout),'--max-rss-bytes',str(limit)]
            if failure:cmd+=['--test-failure',failure]
            cp=subprocess.run(cmd,capture_output=True,text=True)
            s=json.loads((d/'supervisor.json').read_text())
            expected=failure if failure in ('timeout','memory_limit') else 'failed' if failure else 'completed'
            assert s['status']==expected,(name,s['status'],cp.stderr)
            assert s['E05_started'] is False
            row={'name':name,'command':cmd,'expected':expected,'observed':s['status'],'returncode':cp.returncode,'passed':True}
            if not failure:
                w=json.loads((d/'worker.json').read_text())
                assert w['T_total_ns']==w['timer_end_ns']-w['timer_start_ns']>0
                assert w['runtime_setup_in_T_total'] and w['metrics']['top_level_elapsed_ns']<=w['T_total_ns']
                spans=w['metrics']['spans'];parents=[x for x in spans if x['parent'] is None];assert len(parents)==1
                for i,x in enumerate(spans):
                    assert x['end_ns']>=x['start_ns']
                    if x['parent'] is not None:
                        p=spans[x['parent']];assert p['start_ns']<=x['start_ns']<=x['end_ns']<=p['end_ns']
                assert w['peak_tree_upper_bound_bytes']>=w['peak_self_rss_bytes']>0
                if w['mode']=='cold':assert len(w['embedding_calls'])==2 and all(x['exit_code']==0 for x in w['embedding_calls'])
                row.update(T_total_ns=w['T_total_ns'],embedding_calls=len(w['embedding_calls']),scope='Clock/resource accounting check only; timings not compared across methods.')
            results.append(row);print(name,'pass',flush=True)
        a=json.loads((A/'infrastructure_cold_01/worker.json').read_text());b=json.loads((A/'infrastructure_cold_02/worker.json').read_text())
        assert a['embedding_vector_digest']==b['embedding_vector_digest'] and a['outputs']==b['outputs']
        report={'all_checks_passed':True,'results':results,'cold_vector_bits_repeatable_in_two_smokes':True,'E05_started':False,
            'limits':'Two finite cold runs establish this smoke reproducibility only. RSS sampled peak is a lower bound; sequential-child rusage bound is conservative. No superiority/precision inference.'}
    except BaseException:report={'all_checks_passed':False,'results':results,'failure':traceback.format_exc(),'E05_started':False};print(report['failure'])
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    if not report['all_checks_passed']:raise SystemExit(1)
if __name__=='__main__':main()
