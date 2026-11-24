#!/usr/bin/env python3
"""E06 read-only analysis of E05 raw observations and separate diagnostics."""
import collections, json, math, os, statistics
from pathlib import Path
os.environ.update({k:'1' for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','VECLIB_MAXIMUM_THREADS']})
import numpy as np
from e05_common import ROOT, sha, dump_new
from e05_statistics import interval, precision

A=ROOT/'reports/e_stages/E06/E06_2026-11-18_01'
OUT=ROOT/'results/comparison/E06_2026-11-18_01'
E05=ROOT/'reports/e_stages/E05/E05_2026-11-18_01'

def med(xs):return float(statistics.median(xs)) if xs else None
def gm(xs):return math.exp(statistics.mean(math.log(x) for x in xs))
def span_totals(metrics, exclusive=False):
    result=collections.Counter();spans=metrics['spans']
    for i,s in enumerate(spans):
        value=s['end_ns']-s['start_ns']
        if exclusive:value-=sum(t['end_ns']-t['start_ns'] for t in spans if t['parent']==i)
        assert value>=0
        result[s['name']]+=value/1e9
    return dict(result)

def counts_sum(metrics):
    result=collections.Counter()
    for m in metrics:result.update(m['counts'])
    return dict(result)

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    protocol=json.loads((ROOT/'protocol/pilot_v1.json').read_text())
    original=json.loads((E05/'analysis.json').read_text())
    rows=[json.loads(s) for s in (ROOT/'results/pilot_runs.jsonl').read_text().splitlines()]
    measured=[r for r in rows if r['phase']=='measured'];details=[];lookup={};groups=collections.defaultdict(list)
    for r in measured:
        groups[r['case_id'],r['method']].append(r)
        if r['status']!='completed':continue
        path=ROOT/r['path'];assert sha(path/'worker.json')==r['worker_sha256'] and sha(path/'validation.json')==r['validation_sha256']
        w=json.loads((path/'worker.json').read_text());v=json.loads((path/'validation.json').read_text())
        expected=json.loads((ROOT/v['expected_path']).read_text());assert w['outputs']==expected['outputs'] and sha(ROOT/v['expected_path'])==v['expected_sha256']
        total=w['T_total_ns']/1e9;outer=span_totals(w['metrics']);outer.pop('lifecycle_total')
        runtime=w['runtime_import_and_thread_setup_ns']/1e9
        residual=total-runtime-sum(outer.values());assert residual>=-1e-9
        phases=[]
        for i,m in enumerate(w['engine_metrics']):
            exclusive=span_totals(m,True);inclusive=span_totals(m)
            assert abs(sum(exclusive.values())-m['top_level_elapsed_ns']/1e9)<1e-8
            phases.append({'index':i,'exclusive_seconds':exclusive,'inclusive_seconds':inclusive,'counts':m['counts']})
        updates=phases[1:];incl=collections.Counter();excl=collections.Counter()
        for x in phases:incl.update(x['inclusive_seconds']);excl.update(x['exclusive_seconds'])
        reads=[s for s in w['metrics']['spans'] if s['name']=='scheduled_reads']
        elapsed=[(s['end_ns']-w['timer_start_ns'])/1e9 for s in reads]
        fixed=elapsed[0]+total-elapsed[-1];cycles=[elapsed[i]-elapsed[i-1] for i in range(1,len(elapsed))]
        assert abs(fixed+sum(cycles)-total)<1e-8
        emb=sum(x['wall_ns'] for x in w['embedding_calls'])/1e9
        engine=outer['initialization']+outer.get('maintenance',0)
        detail={'run_id':r['run_id'],'case_id':r['case_id'],'method':r['method'],'block':r['block'],'total_seconds':total,
                'disjoint_outer_seconds':dict(outer,runtime_setup=runtime,unspanned=residual),
                'engine_inclusive_seconds':dict(incl),'engine_exclusive_seconds':dict(excl),'phases':phases,
                'build_counts':phases[0]['counts'],'update_counts':counts_sum(w['engine_metrics'][1:]),
                'embedding_seconds':emb,'engine_fraction':engine/total,'nonengine_floor_ratio':1-engine/total,
                'no_certificate_and_partition_seconds':total-incl.get('certificates',0)-incl.get('partition_build',0),
                'fixed_lifecycle_seconds':fixed,'mean_observed_cycle_seconds':statistics.mean(cycles),'cycles':len(cycles),
                'prefix_seconds':elapsed[:-1]+[total]}
        assert detail['no_certificate_and_partition_seconds']>0
        details.append(detail);lookup[r['case_id'],r['method'],r['block']]=detail
    recalculated=precision(rows,protocol,40)
    assert recalculated==original['precision']
    summary=[]
    for case in protocol['cases']:
        for method in case['methods']:
            rs=groups[case['id'],method];ds=[lookup[case['id'],method,r['block']] for r in rs if r['status']=='completed']
            s={'case_id':case['id'],'method':method,'status_counts':dict(collections.Counter(r['status'] for r in rs)),
               'runs':len(rs),'complete':len(ds)==len(rs),'median_total_seconds':med([d['total_seconds'] for d in ds]),
               'total_geomean_seconds':gm([d['total_seconds'] for d in ds]) if ds else None}
            for target,key in [('outer','disjoint_outer_seconds'),('exclusive','engine_exclusive_seconds'),('inclusive','engine_inclusive_seconds'),('build_counts','build_counts'),('update_counts','update_counts')]:
                keys=sorted({k for d in ds for k in d[key]})
                s[target]={k:med([d[key].get(k,0) for d in ds]) for k in keys}
            s['embedding_fraction_median']=med([d['embedding_seconds']/d['total_seconds'] for d in ds])
            s['engine_fraction_median']=med([d['engine_fraction'] for d in ds])
            s['mean_fixed_seconds']=statistics.mean(d['fixed_lifecycle_seconds'] for d in ds) if ds else None
            s['mean_cycle_seconds']=statistics.mean(d['mean_observed_cycle_seconds'] for d in ds) if ds else None
            summary.append(s)
    by={(s['case_id'],s['method']):s for s in summary};contrasts=[];floors=[];free_cert=[];prefix=[];horizon=[]
    for ci,case in enumerate(protocol['cases']):
        n=len(groups[case['id'],'C1'])
        for mi,method in enumerate(case['methods']):
            if method=='C1':continue
            pair=[(lookup.get((case['id'],'C1',b)),lookup.get((case['id'],method,b))) for b in range(1,n+1)]
            if not all(a and b for a,b in pair):
                contrasts.append({'case_id':case['id'],'baseline':method,'estimable':False,'reason':'Incomplete paired series; timeout retained, no speedup'});continue
            stat=interval([math.log(a['total_seconds']/b['total_seconds']) for a,b in pair],18061801+ci*100+mi)
            stat.update(case_id=case['id'],baseline=method,confirmatory=False,resource_probe=n<20)
            contrasts.append(stat)
            floor=interval([math.log(b['nonengine_floor_ratio']) for a,b in pair],18061802+ci*100+mi)
            floor.update(case_id=case['id'],baseline=method,assumption='All observed baseline non-engine costs held fixed; initialization AND maintenance made zero. Conditional optimistic model, not a future runtime bound.')
            floors.append(floor)
            free=interval([math.log(a['no_certificate_and_partition_seconds']/b['total_seconds']) for a,b in pair],18061803+ci*100+mi)
            free.update(case_id=case['id'],baseline=method,assumption='C1 certificate and partition spans made free, all other C1 and baseline observations fixed; not an implemented algorithm.')
            free_cert.append(free)
            ratios=np.exp(np.mean([[math.log(x/y) for x,y in zip(a['prefix_seconds'],b['prefix_seconds'])] for a,b in pair],axis=0)).tolist()
            prefix.append({'case_id':case['id'],'baseline':method,'ratios':ratios,
                           'first_sustained_below_1':next((i for i in range(len(ratios)) if all(x<1 for x in ratios[i:])),None),
                           'first_sustained_at_most_0_90':next((i for i in range(len(ratios)) if all(x<=.9 for x in ratios[i:])),None)})
            cs=by[case['id'],'C1'];bs=by[case['id'],method];entries={}
            for target in [1.,.9]:
                intercept=cs['mean_fixed_seconds']-target*bs['mean_fixed_seconds'];slope=cs['mean_cycle_seconds']-target*bs['mean_cycle_seconds']
                entries[str(target)]={'intercept_seconds':intercept,'slope_seconds_per_batch':slope,
                    'eventual_threshold_batches':max(0,math.ceil(intercept/-slope)) if slope<0 else None,
                    'eventual_success_in_affine_model':slope<0 or (slope==0 and intercept<=0)}
            horizon.append({'case_id':case['id'],'baseline':method,'targets':entries,
                'assumption':'Hypothetical stationary repetition of observed mean cycle cost, unchanged fixed cost. Real evolving histories/cache/geometry can differ; not a measured amortization threshold.'})
    cold=[c for c in protocol['cases'] if c['role']=='primary_cold'];aggregate_floors=[];aggregate_free=[]
    for mi,method in enumerate(protocol['mandatory_methods']):
        f=[];z=[]
        for b in range(1,41):
            f.append(statistics.mean(math.log(lookup[c['id'],method,b]['nonengine_floor_ratio']) for c in cold))
            z.append(statistics.mean(math.log(lookup[c['id'],'C1',b]['no_certificate_and_partition_seconds']/lookup[c['id'],method,b]['total_seconds']) for c in cold))
        stat=interval(f,18061901+mi);stat.update(baseline=method);aggregate_floors.append(stat)
        stat=interval(z,18061921+mi);stat.update(baseline=method);aggregate_free.append(stat)
    profile_index=json.loads((OUT/'profile_index.json').read_text());assert profile_index['all_completed'];profiles=[]
    for r in profile_index['records']:
        path=OUT/'profiles'/r['run_id']/'profile.json';assert sha(path)==r['profile_sha256'];d=json.loads(path.read_text())
        assert d['full_outputs_match'] and d['numeric_guards_enabled'] and not d['performance_series']
        sums=collections.Counter();calls=collections.Counter();reasons=collections.Counter();bound_results=collections.Counter()
        for e in d['events']:
            name=('build/' if e['phase']=='build' else 'updates/')+e['name'];sums[name]+=e['elapsed_ns']/1e9;calls[name]+=1
            if e['name']=='bounds':bound_results[e['result']]+=1
        for c in d['coverage']:reasons[c['reason']+('/certified' if c['certified'] else '/rejected')]+=1
        profiles.append({'run_id':r['run_id'],'case_id':d['case_id'],'method':d['method'],'call_seconds_inclusive_do_not_sum':dict(sums),
                         'calls':dict(calls),'coverage_reasons':dict(reasons),'bound_results':dict(bound_results),
                         'blocks':d['blocks'],'short_registry_counts':d['short_registry_counts'],'correct':True})
    dump_new(OUT/'run_analysis.json',details)
    result={'version':'A-E06-analysis-1.0','input_index_sha256':sha(ROOT/'results/pilot_runs.jsonl'),
        'measured_runs':len(measured),'completed_runs':len(details),'statuses':dict(collections.Counter(r['status'] for r in measured)),
        'full_output_mismatches':0,'original_primary_statistics_reproduced':True,'summary':summary,'contrasts':contrasts,
        'primary_statistics':recalculated,'conditional_nonengine_floors':floors,'conditional_cold_aggregate_floors':aggregate_floors,
        'zero_certificate_partition_counterfactual':free_cert,'zero_certificate_partition_cold_aggregate':aggregate_free,
        'observed_prefixes':prefix,'conditional_horizon_models':horizon,'profile_summary':profiles,
        'noise':original['noise'],'event_trace':original['event_trace'],'E07_started':False,
        'final_holdout_accessed':False,'new_scientific_performance_runs':0}
    dump_new(OUT/'analysis.json',result)
    # A descriptive plot uses means of disjoint costs, preserving additive totals.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,3,figsize=(13,4.8))
    for ax,case_id in zip(axes,['P01_cold_local_11','P05_ready_dominated_11','P07_ready_scale_128']):
        methods=['C1','B1_DELTA_MATRIX','B2_RESERVE_EXACT','B3_ALL_SCORES'];bottom=np.zeros(len(methods))
        for label,color,fn in [
            ('Outside engine','#6b93b5',lambda d:d['total_seconds']-d['disjoint_outer_seconds']['initialization']-d['disjoint_outer_seconds']['maintenance']),
            ('Build/init','#cda45b',lambda d:d['disjoint_outer_seconds']['initialization']),
            ('Certificates','#b85858',lambda d:d['engine_inclusive_seconds'].get('certificates',0)),
            ('Other updates','#79a676',lambda d:d['disjoint_outer_seconds']['maintenance']-d['engine_inclusive_seconds'].get('certificates',0))]:
            values=np.array([statistics.mean(fn(d) for d in details if d['case_id']==case_id and d['method']==m) for m in methods])
            ax.bar(range(4),values,bottom=bottom,color=color,label=label);bottom+=values
        ax.set_xticks(range(4),['C1','B1','B2','B3']);ax.set_title(case_id.split('_')[0]+' / '+('cold' if 'cold' in case_id else 'ready vectors'));ax.set_ylabel('Mean complete-path time, seconds');ax.grid(axis='y',alpha=.2)
    handles,labels=axes[0].get_legend_handles_labels();fig.legend(handles,labels,loc='lower center',ncol=4)
    fig.suptitle('E06 diagnosis from E05: disjoint costs, 40 measured blocks per method')
    fig.tight_layout(rect=[0,.09,1,.93]);fig.savefig(OUT/'cost_components.png',dpi=180);plt.close(fig)
    print(json.dumps({'measured_runs':len(measured),'completed':len(details),'primary_reproduced':True,'profiles':len(profiles),'E07_started':False}))

if __name__=='__main__':main()
