#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Post-run mechanism, timing-environment and resource diagnostics, not a gate."""
import collections,json,math,statistics
from e07_common import ROOT,sha,dump_new
A=ROOT/'reports/e_stages/E07/E07_2026-11-18_01'
OUT=ROOT/'results/iterations/E07_2026-11-18_01'
def gm(xs):return math.exp(statistics.mean(math.log(x) for x in xs))
def med(xs):return statistics.median(xs) if xs else None
def main():
    allrows=[json.loads(s) for s in (OUT/'runs.jsonl').read_text().splitlines()]
    mechanisms=[];resources=[];environment=[]
    for phase in ['I01','regressions']:
        analysis=json.loads((OUT/(phase+'_analysis.json')).read_text())
        details=json.loads((OUT/(phase+'_run_analysis.json')).read_text())
        measured=[d for d in details if not d['warmup']]
        by={(d['case_id'],d['label'],d['block']):d for d in measured}
        for case in sorted({d['case_id'] for d in measured}):
            pairs=[]
            for key,new in by.items():
                if key[0]!=case or key[1]!='C1_I01':continue
                old=by.get((case,'C1_ORIGINAL',key[2]))
                if old:pairs.append((new,old))
            item={'phase':phase,'case':case,'paired_blocks':len(pairs),
                  'operation_counts_identical':all(n['counts']==o['counts'] for n,o in pairs),
                  'update_counts_identical':all(n['update_counts']==o['update_counts'] for n,o in pairs)}
            for field in ['partition_build','full_search']:
                ps=[(n['build_seconds'].get(field,0),o['build_seconds'].get(field,0)) for n,o in pairs]
                item[field]={'new_median_seconds':med([n for n,o in ps]),'old_median_seconds':med([o for n,o in ps]),
                    'paired_geomean_ratio':gm([n/o for n,o in ps]) if ps and all(n>0 and o>0 for n,o in ps) else None}
            item['full_path_ratio']=gm([n['T_total_seconds']/o['T_total_seconds'] for n,o in pairs]) if pairs else None
            item['saved_partition_fraction_of_old_total_median']=med([(o['build_seconds'].get('partition_build',0)-n['build_seconds'].get('partition_build',0))/o['T_total_seconds'] for n,o in pairs])
            mechanisms.append(item)
        for s in analysis['summary']:
            base=next((b for b in analysis['summary'] if b['case_id']==s['case_id'] and b['label']=='B3_ALL_SCORES_I01'),None)
            if not base:continue
            ratios={}
            for field in ['freshness','individual_reads']:
                ratios[field]={k:s[field][k]/base[field][k] if s[field][k] is not None and base[field][k] and base[field][k]>0 else None for k in ['p95_seconds','p99_seconds']}
            ratios['sampled_whole_life_peak_ratio']=s['sampled_whole_life_peak_max_bytes']/base['sampled_whole_life_peak_max_bytes'] if s['sampled_whole_life_peak_max_bytes'] and base['sampled_whole_life_peak_max_bytes'] else None
            ratios['conservative_upper_ratio']=s['operational_tree_upper_max_bytes']/base['operational_tree_upper_max_bytes'] if s['operational_tree_upper_max_bytes'] and base['operational_tree_upper_max_bytes'] else None
            resources.append({'phase':phase,'case':s['case_id'],'label':s['label'],'complete':s['complete'],'diagnostic_reference':'B3_ALL_SCORES_I01, not validation-selected B*','ratios':ratios,
                'rss_ratio_certified':False,'tail_assurance':False,'reason':'Different memory windows; samples and conservative upper bounds do not establish true peak ratio. No held-out B* selected.'})
        for key in sorted({(d['case_id'],d['label']) for d in measured}):
            ds=sorted([d for d in measured if (d['case_id'],d['label'])==key],key=lambda d:d['block'])
            ts=[d['T_total_seconds'] for d in ds];n=len(ts);half=n//2
            provenances=[json.loads((ROOT/d['path']/'provenance.json').read_text()) for d in ds]
            logs=[math.log(t) for t in ts];mean=statistics.mean(logs);den=sum((t-mean)**2 for t in logs)
            environment.append({'phase':phase,'case':key[0],'label':key[1],'complete_measured_runs':n,
                'first_half_gmean_seconds':gm(ts[:half]) if half else None,'second_half_gmean_seconds':gm(ts[half:]) if half else None,
                'second_first_ratio':gm(ts[half:])/gm(ts[:half]) if half else None,
                'lag1_log_time_descriptive':sum((logs[i]-mean)*(logs[i-1]-mean) for i in range(1,n))/den if den else None,
                'load1_min':min(p['background_load'][0] for p in provenances),'load1_max':max(p['background_load'][0] for p in provenances),
                'thermal_log_variants':sorted({p['thermal_stdout'].strip() for p in provenances})})
    dump_new(OUT/'mechanism_audit.json',{'records':mechanisms,'all_operation_counts_identical':all(x['operation_counts_identical'] and x['update_counts_identical'] for x in mechanisms),
        'engineering_build_cost_reduced_all_cases':all(x['partition_build']['paired_geomean_ratio']<1 for x in mechanisms),'novelty_claim':False,'E08_started':False})
    dump_new(OUT/'resource_diagnostics.json',{'records':resources,'formal_constraints_passed':False,'interpretation':'Descriptive development diagnostics. None substitutes for frozen B* on validation, correct memory peak estimation or sufficient tail precision.','E08_started':False})
    dump_new(OUT/'timing_environment.json',{'records':environment,'stationarity_proved':False,'interpretation':'Randomized sequential blocks on shared workstation; recorded background contention. Descriptive drift/autocorrelation checks do not prove exchangeability or bootstrap coverage.','E08_started':False})
    counts=collections.Counter((r['phase'],r['warmup'],r['status']) for r in allrows)
    dump_new(A/'run_accounting.json',{'runs':len(allrows),'counts':[{'phase':p,'warmup':w,'status':s,'runs':n} for (p,w,s),n in sorted(counts.items())],
        'completed_snapshots':sum(r.get('snapshots',0) for r in allrows),'completed_query_outputs':sum(r.get('query_outputs',0) for r in allrows),
        'measured_snapshots':sum(r.get('snapshots',0) for r in allrows if not r['warmup']),
        'measured_query_outputs':sum(r.get('query_outputs',0) for r in allrows if not r['warmup']),
        'output_mismatches':sum(r.get('correct') is False for r in allrows),'index_sha256':sha(OUT/'runs.jsonl'),'E08_started':False})
    print(json.dumps({'mechanism_cases':len(mechanisms),'resources':len(resources),'runs':len(allrows)}))
if __name__=='__main__':main()
