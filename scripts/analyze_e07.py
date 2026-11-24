#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Analyze immutable E07 runs; headroom and scientific success are separate."""
import argparse,collections,json,math,os,statistics
os.environ.update({k:'1' for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','VECLIB_MAXIMUM_THREADS']})
import numpy as np
from e05_common import ROOT,sha,dump_new
from e05_statistics import interval
A=ROOT/'reports/e_stages/E07/E07_2026-11-18_01';OUT=ROOT/'results/iterations/E07_2026-11-18_01'

def med(xs):return float(statistics.median(xs)) if xs else None
def gm(xs):return math.exp(statistics.mean(math.log(x) for x in xs))
def load_runs(phase):
    rows=[json.loads(x) for x in (OUT/'runs.jsonl').read_text().splitlines()];rows=[r for r in rows if r['phase']==phase]
    details=[]
    for r in rows:
        if r['status']!='completed':continue
        base=ROOT/r['path'];assert sha(base/'worker.json')==r['worker_sha256'];w=json.loads((base/'worker.json').read_text());v=json.loads((base/'validation.json').read_text())
        assert v['all_outputs_match'] and sha(ROOT/v['expected_path'])==v['expected_sha256']
        totals=collections.Counter();build=collections.Counter();update=collections.Counter();counts=collections.Counter();update_counts=collections.Counter()
        for s in w['metrics']['spans']:
            if s['name']!='lifecycle_total':totals[s['name']]+=(s['end_ns']-s['start_ns'])/1e9
        for i,m in enumerate(w['engine_metrics']):
            for s in m['spans']:(build if i==0 else update)[s['name']]+=(s['end_ns']-s['start_ns'])/1e9
            counts.update(m['counts'])
            if i:update_counts.update(m['counts'])
        T=w['T_total_ns']/1e9;engine=totals['initialization']+totals['maintenance']
        prep=[s for s in w['metrics']['spans'] if s['name']=='delta_preparation'];maint=[s for s in w['metrics']['spans'] if s['name']=='maintenance']
        freshness=[(m['end_ns']-p['start_ns'])/1e9 for p,m in zip(prep,maint)]
        details.append(dict(r,T_total_seconds=T,components_seconds=dict(totals),build_seconds=dict(build),update_seconds=dict(update),counts=dict(counts),update_counts=dict(update_counts),
            engine_fraction=engine/T,conditional_nonengine_floor=1-engine/T,embedding_fraction=sum(x['wall_ns'] for x in w['embedding_calls'])/w['T_total_ns'],
            freshness_seconds=freshness,individual_read_seconds=[x/1e9 for x in w['read_latency_ns']]))
    return rows,details

def summary(rows,details):
    groups=collections.defaultdict(list);dg=collections.defaultdict(list)
    for r in rows:
        if not r['warmup']:groups[r['case_id'],r['label']].append(r)
    for d in details:
        if not d['warmup']:dg[d['case_id'],d['label']].append(d)
    out=[]
    for (cid,label),rs in sorted(groups.items()):
        ds=dg[cid,label];s={'case_id':cid,'label':label,'runs':len(rs),'status_counts':dict(collections.Counter(r['status'] for r in rs)),
            'complete':len(ds)==len(rs),'median_T_total_seconds':med([d['T_total_seconds'] for d in ds]),
            'geomean_T_total_seconds':gm([d['T_total_seconds'] for d in ds]) if ds else None,
            'median_engine_fraction':med([d['engine_fraction'] for d in ds]),'median_embedding_fraction':med([d['embedding_fraction'] for d in ds])}
        for field in ['components_seconds','build_seconds','update_seconds','counts','update_counts']:
            keys=sorted({k for d in ds for k in d[field]});s['median_'+field]={k:med([d[field].get(k,0) for d in ds]) for k in keys}
        fresh=[x for d in ds for x in d['freshness_seconds']];reads=[x for d in ds for x in d['individual_read_seconds']]
        s['freshness']={'samples':len(fresh),'p95_seconds':float(np.quantile(fresh,.95)) if fresh else None,'p99_seconds':float(np.quantile(fresh,.99)) if fresh else None,'max_seconds':max(fresh) if fresh else None}
        s['individual_reads']={'samples':len(reads),'p95_seconds':float(np.quantile(reads,.95)) if reads else None,'p99_seconds':float(np.quantile(reads,.99)) if reads else None,'max_seconds':max(reads) if reads else None,'tail_assurance':False}
        s['operational_tree_upper_max_bytes']=max((d['operational_tree_upper_bytes'] for d in ds),default=None)
        s['sampled_whole_life_peak_max_bytes']=max((d['sampled_whole_life_peak_bytes'] for d in ds),default=None)
        out.append(s)
    return out

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--phase',required=True,choices=['headroom','I01','regressions']);args=ap.parse_args();phase=args.phase
    done=json.loads((A/('execution_'+phase+'_complete.json')).read_text());rows,details=load_runs(phase);policy=json.loads((ROOT/'protocol/improvement_policy.json').read_text())
    measured=[d for d in details if not d['warmup']];groups=summary(rows,details)
    result={'phase':phase,'version':'A-E07-analysis-1.0','index_sha256_at_analysis':sha(OUT/'runs.jsonl'),'measured_runs':sum(not r['warmup'] for r in rows),
        'warmup_runs':sum(r['warmup'] for r in rows),'measured_statuses':dict(collections.Counter(r['status'] for r in rows if not r['warmup'])),
        'snapshots_checked':sum(d['snapshots'] for d in measured),'query_outputs_checked':sum(d['query_outputs'] for d in measured),
        'summary':groups,'E08_started':False,'validation_accessed':False,'final_holdout_accessed':False}
    lookup={(d['case_id'],d['label'],d['block']):d for d in measured}
    if phase=='headroom':
        cases=json.loads((OUT/'workload_manifest.json').read_text())['cases'];blocks=[]
        for b in range(1,policy['headroom']['measured_blocks']+1):
            ds=[lookup.get((c['id'],'B3_HEADROOM',b)) for c in cases]
            if all(ds):blocks.append({'block':b,'equal_family_floor':gm([d['conditional_nonengine_floor'] for d in ds]),'families':len(ds)})
        complete=len(blocks)==policy['headroom']['measured_blocks'];stop=complete and all(b['equal_family_floor']>.9 for b in blocks)
        result.update(equal_family_blocks=blocks,complete_headroom_matrix=complete,conditional_search_budget_stop=stop,
            decision='Perform requested I01 cleanup and matched comparisons; defer I02/I03 because every complete block has <10% engine-only headroom.' if stop else 'Headroom does not trigger predefined stop; assess I01 then bounded I02/I03 if needed.',
            interpretation='Conditional fixed-other-cost ceiling, three repeated blocks on 14 fixed families. Not a proof of universal impossibility or a final validation result.')
        if complete:result['aggregate_floor']=interval([math.log(b['equal_family_floor']) for b in blocks],18071901)
        dump_new(A/'headroom_decision.json',{k:v for k,v in result.items() if k not in ['summary']})
    else:
        cases=sorted({r['case_id'] for r in rows});contrasts=[];aggregate=[]
        labels=sorted({r['label'] for r in rows if r['label']!='C1_I01'})
        for ci,c in enumerate(cases):
            for li,label in enumerate(labels):
                blocks=sorted({r['block'] for r in rows if not r['warmup'] and r['case_id']==c and r['label']==label})
                pairs=[(lookup.get((c,'C1_I01',b)),lookup.get((c,label,b))) for b in blocks]
                if not pairs or not all(x and y for x,y in pairs):contrasts.append({'case_id':c,'baseline':label,'estimable':False,'reason':'Incomplete paired series; failures retained'});continue
                stat=interval([math.log(x['T_total_seconds']/y['T_total_seconds']) for x,y in pairs],18071911+ci*100+li);stat.update(case_id=c,baseline=label)
                contrasts.append(stat)
        for li,label in enumerate(labels):
            blocks=sorted(set.intersection(*[{r['block'] for r in rows if not r['warmup'] and r['case_id']==c and r['label']==label} for c in cases]))
            if not blocks or not all((c,label,b) in lookup and (c,'C1_I01',b) in lookup for c in cases for b in blocks):
                aggregate.append({'baseline':label,'estimable':False,'reason':'Incomplete paired matrix'});continue
            logs=[statistics.mean(math.log(lookup[c,'C1_I01',b]['T_total_seconds']/lookup[c,label,b]['T_total_seconds']) for c in cases) for b in blocks]
            stat=interval(logs,18072001+li);stat.update(baseline=label);aggregate.append(stat)
        promote=phase=='I01' and all(any(x.get('estimable') and x['baseline']==b and x['blocks']>=20 and x['one_sided_bonferroni_upper']<=.9 for x in aggregate) for b in ['B2_RESERVE_EXACT_I01','B3_ALL_SCORES_I01'])
        if promote:promote=all(x.get('estimable') and x['ratio']<=1 for x in contrasts if x['baseline'] in ['B2_RESERVE_EXACT_I01','B3_ALL_SCORES_I01'])
        result.update(contrasts=contrasts,equal_case_aggregate=aggregate,promote_to_validation=promote,
            candidate_success=False,reason='Screening only. Complete mandatory held-out validation/resource/novelty checks required for candidate pass.')
    dump_new(OUT/(phase+'_run_analysis.json'),details)
    dump_new(OUT/(phase+'_analysis.json'),result)
    print(json.dumps({'phase':phase,'measured':result['measured_runs'],'outcomes':result['measured_statuses'],
        'conditional_budget_stop':result.get('conditional_search_budget_stop'),'promote':result.get('promote_to_validation'),'E08_started':False}))
if __name__=='__main__':main()
