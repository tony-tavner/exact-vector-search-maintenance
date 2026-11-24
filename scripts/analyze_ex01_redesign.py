"""Analyze every predeclared EX01 result; no missing-case or warmup selection."""
import collections, gzip, hashlib, json, math, statistics
from pathlib import Path
from e05_common import ROOT, sha, dump_new

A=ROOT/'reports/exploration/EX01_2026-11-18_01'
D=ROOT/'data/derived/EX01_2026-11-18_01'

def gm(values):
    return math.exp(statistics.mean(math.log(x) for x in values)) if values else None

def quantile(values, probability):
    s=sorted(values); x=(len(s)-1)*probability; lo=int(x); hi=math.ceil(x)
    return s[lo]+(s[hi]-s[lo])*(x-lo)

def main():
    completion=json.loads((A/'execution_complete.json').read_text())
    schedule=json.loads((A/'schedule.json').read_text())
    manifest=json.loads((D/'manifest.json').read_text())
    rows=[json.loads(s) for s in (A/'runs.jsonl').read_text().splitlines()]
    assert len(rows)==len(schedule['runs'])==completion['runs']
    assert [r['run_id'] for r in rows]==[r['run_id'] for r in schedule['runs']]
    measured=[r for r in rows if r['phase']=='measured']
    assert len(measured)==96
    derived=[]
    for r in rows:
        z={'run_id':r['run_id'],'status':r['status']}
        if r['status']=='completed':
            assert r['validation']=='passed'
            path=ROOT/r['run_dir']/'worker.json.gz'
            with gzip.open(path,'rt',encoding='utf-8') as f:w=json.load(f)
            assert w['T_total_ns']==r['T_total_ns'] and w['mode']=='ready_vectors'
            for f,h in w['source_hashes'].items(): assert sha(ROOT/f)==h
            spans=collections.Counter()
            for report in w['engine_metrics']:
                for s in report['spans']:spans[s['name']]+=s['end_ns']-s['start_ns']
            certificate_ns=spans['certificates']
            assert 0<=certificate_ns<w['T_total_ns']
            z.update(artifact_sha256=sha(path),certificate_ns=certificate_ns,
                     partition_ns=spans['partition_build'],
                     exclusive_free_certificate_time_ns=w['T_total_ns']-certificate_ns,
                     read_p95_ns=quantile(w['read_latency_ns'],.95),
                     read_p99_ns=quantile(w['read_latency_ns'],.99),
                     rss_operational_upper=w['peak_tree_upper_bound_bytes'],
                     engine_span_ns=dict(spans),
                     span_warning='Named spans can be nested; do not add them to total')
        derived.append(z)
    byrun={r['run_id']:r for r in derived}
    cases=[]
    for c in manifest['cases']:
        rs=[r for r in measured if r['case_id']==c['id']]
        assert len(rs)==6
        pairs=[]
        for block in [1,2,3]:
            pair={r['method']:r for r in rs if r['block']==block}
            assert set(pair)=={'C1','B3_ALL_SCORES'}
            x=pair['C1'];y=pair['B3_ALL_SCORES'];valid=all(r['status']=='completed' and r.get('validation')=='passed' for r in pair.values())
            z={'block':block,'complete_correct':valid,'C1_status':x['status'],'B3_status':y['status']}
            if valid:
                xd=byrun[x['run_id']];yd=byrun[y['run_id']]
                z.update(ratio=x['T_total_ns']/y['T_total_ns'], C1_seconds=x['T_total_ns']/1e9,
                    B3_seconds=y['T_total_ns']/1e9,
                    free_certificate_counterfactual_ratio=xd['exclusive_free_certificate_time_ns']/y['T_total_ns'],
                    C1_certificate_fraction=xd['certificate_ns']/x['T_total_ns'],
                    C1_certified_cells=x['certified_cells'],C1_bound_pairs=x['bound_pairs'],
                    C1_score_pairs=x['score_pairs'],B3_score_pairs=y['score_pairs'],
                    p95_ratio=xd['read_p95_ns']/yd['read_p95_ns'],p99_ratio=xd['read_p99_ns']/yd['read_p99_ns'],
                    RSS_ratio=xd['rss_operational_upper']/yd['rss_operational_upper'])
            pairs.append(z)
        complete=all(z['complete_correct'] for z in pairs)
        out={k:c[k] for k in ['id','family','group_size','horizon','initial_documents','initial_fragments','queries']}
        out.update(complete_correct=complete,pairs=pairs,ratio=None,
                   C1_completed=sum(r['status']=='completed' for r in rs if r['method']=='C1'),
                   B3_completed=sum(r['status']=='completed' for r in rs if r['method']=='B3_ALL_SCORES'))
        if complete:
            ratios=[z['ratio'] for z in pairs]
            out.update(ratio=gm(ratios),paired_ratio_min=min(ratios),paired_ratio_max=max(ratios),
                free_certificate_counterfactual_ratio=gm([z['free_certificate_counterfactual_ratio'] for z in pairs]),
                C1_certificate_fraction=statistics.mean(z['C1_certificate_fraction'] for z in pairs),
                C1_seconds_median=statistics.median(z['C1_seconds'] for z in pairs),
                B3_seconds_median=statistics.median(z['B3_seconds'] for z in pairs),
                C1_certified_cells=pairs[0]['C1_certified_cells'],C1_bound_pairs=pairs[0]['C1_bound_pairs'],
                C1_score_pairs=pairs[0]['C1_score_pairs'],B3_score_pairs=pairs[0]['B3_score_pairs'])
            for name in ['C1_certified_cells','C1_bound_pairs','C1_score_pairs','B3_score_pairs']:
                assert len({z[name] for z in pairs})==1
        cases.append(out)
    regimes=[]
    for g in [1,4]:
        for h in [100,1000]:
            cs=[c for c in cases if c['group_size']==g and c['horizon']==h];assert len(cs)==4
            complete=all(c['complete_correct'] for c in cs)
            ratio=gm([c['ratio'] for c in cs]) if complete else None
            worst=max(c['ratio'] for c in cs) if complete else None
            regimes.append({'group_size':g,'horizon':h,'complete_correct':complete,'ratio':ratio,'worst_family_ratio':worst,
                'shortlisted':complete and ratio<=.85 and worst<=.95,'families':[c['family'] for c in cs],
                'reason':'All four families must complete, geomean <=0.85 and every family <=0.95; exploratory only'})
    status_counts=dict(collections.Counter(r['status'] for r in rows))
    summary={'id':'EX01_2026-11-18_01','scope':'exploratory ready-vector screen; no physical embeddings or full-path superiority inference',
        'inputs':{str(p.relative_to(ROOT)):sha(p) for p in [A/'policy.json',A/'schedule.json',D/'manifest.json',A/'runs.jsonl',A/'oracle_manifest.json']},
        'planned_runs':128,'recorded_runs':len(rows),'warmup_runs':32,'measured_runs':len(measured),
        'status_counts':status_counts,'verified_answers':sum(r.get('answers',0) for r in rows),
        'mismatches':0,'runs_with_unavailable_validation':sum(r['status']!='completed' for r in rows),
        'regimes':regimes,'cases':cases,'shortlisted_regimes':[r for r in regimes if r['shortlisted']],
        'method_or_numerical_changes':False,'physical_embeddings_executed':False,'independent_confirmation':False,
        'E03_started':False,'E08_started':False,'confidence_interval':None,
        'uncertainty':'Three measured blocks and exposed development data; descriptive paired ratios, no final significance or superiority claim',
        'counterfactual_scope':'Subtract only directly timed certificate spans from C1 total. Diagnostic additive counterfactual, not an implemented method or global attainable bound.'}
    dump_new(A/'run_diagnostics.json',derived)
    dump_new(A/'analysis.json',summary)
    print(json.dumps({k:summary[k] for k in ['recorded_runs','status_counts','verified_answers','regimes','shortlisted_regimes']},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
