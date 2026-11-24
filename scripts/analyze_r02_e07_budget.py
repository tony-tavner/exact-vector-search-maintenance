#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E02 reassessment: arithmetic over immutable E07 evidence, no new experiment."""
import collections,hashlib,json,math,statistics
from pathlib import Path
R=Path(__file__).resolve().parents[1]
A=R/'reports/e_stages/R02/R02_2026-11-18_03'
E=R/'reports/e_stages/E02/E02_2026-11-18_02'
O=R/'results/iterations/E07_2026-11-18_01'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
def save(p,x):
    assert not p.exists();p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def gm(xs):return math.exp(statistics.mean(math.log(x) for x in xs))
def root(f,target=.9):
    lo=1e-12;hi=1.
    assert f(lo)<target<f(hi)
    for _ in range(80):
        mid=(lo+hi)/2
        if f(mid)>target:hi=mid
        else:lo=mid
    return (lo+hi)/2
def main():
    rows=[json.loads(s) for s in (O/'runs.jsonl').read_text().splitlines()]
    rows=[x for x in rows if not x['warmup'] and x['status']=='completed']
    details=[];workers={};hashes={}
    for row in rows:
        if row['phase']!='headroom' and not (row['phase']=='I01' and row['label'] in ['C1_I01','C1_ORIGINAL','C1_NO_CERT_I01','B2_RESERVE_EXACT_I01','B3_ALL_SCORES_I01']):continue
        path=R/row['path']/'worker.json';w=read(path);assert sha(path)==row['worker_sha256'];hashes[str(path.relative_to(R))]=row['worker_sha256']
        spans=w['metrics']['spans'];cost=collections.Counter()
        for s in spans:
            if s['name']!='lifecycle_total':cost[s['name']]+=(s['end_ns']-s['start_ns'])/1e9
        T=w['T_total_ns']/1e9;engine=cost['initialization']+cost['maintenance'];common=T-engine
        emb=sum(c['wall_ns'] for c in w['embedding_calls'])/1e9
        assert 0<engine<T and 0<emb<=common
        cert=sum((s['end_ns']-s['start_ns'])/1e9 for m in w['engine_metrics'][1:] for s in m['spans'] if s['name']=='certificates')
        partition=sum((s['end_ns']-s['start_ns'])/1e9 for s in w['engine_metrics'][0]['spans'] if s['name']=='partition_build')
        assert 0<=cert+partition<T
        item={'run_id':row['run_id'],'case':row['case_id'],'block':row['block'],'phase':row['phase'],'label':row['label'],
            'T':T,'engine':engine,'common':common,'physical_embedding_wall':emb,'other_common':common-emb,'certificates':cert,'partition':partition}
        details.append(item);workers[row['case_id'],row['block'],row['label']]=item
    head=[x for x in details if x['phase']=='headroom'];assert len(head)==42
    floor=gm([x['common']/x['T'] for x in head]);old=read(O/'headroom_analysis.json');assert abs(floor-old['aggregate_floor']['ratio'])<1e-12
    def ratio(xs,a,rho):return gm([(a*x['common']+rho*x['engine'])/(a*x['common']+x['engine']) for x in xs])
    grids=[]
    for rho in [0,.25,.5,.75]:
        a=root(lambda a:ratio(head,a,rho));bs=[root(lambda a:ratio([x for x in head if x['block']==b],a,rho)) for b in [1,2,3]]
        grids.append({'candidate_engine_fraction_of_B3':rho,'max_shared_remaining_nonengine_fraction_for_ratio_0_90':a,
            'required_shared_nonengine_reduction':1-a,'per_block_required_reduction':[1-v for v in bs],
            'fixed_grid':[{'shared_remaining_fraction':z,'aggregate_ratio':ratio(head,z,rho)} for z in [1,.75,.5,.25]],
            'interpretation':'Counterfactual uniform factor for all nonengine costs in both methods; not an observed optimization.'})
    families=[]
    for case in sorted({x['case'] for x in head}):
        xs=[x for x in head if x['case']==case];f=gm([x['common']/x['T'] for x in xs])
        rho=root(lambda rho:ratio(xs,1,rho)) if f<.9 else None
        families.append({'case':case,'conditional_maximum_engine_only_saving':1-f,
            'max_residual_engine_fraction_for_own_10_percent':rho,'required_engine_reduction_if_possible':None if rho is None else 1-rho,
            'median_embedding_share':statistics.median(x['physical_embedding_wall']/x['T'] for x in xs),
            'median_engine_share':statistics.median(x['engine']/x['T'] for x in xs)})
    paired=[]
    for case in ['T100_SOC_25','T100_SOC_27']:
        for b in range(1,21):
            c=workers[case,b,'C1_I01'];base=workers[case,b,'B3_ALL_SCORES_I01'];nc=workers[case,b,'C1_NO_CERT_I01']
            paired.append({'case':case,'block':b,'C1_vs_B3':c['T']/base['T'],'no_certificate_vs_B3_measured':nc['T']/base['T'],
                'free_certificates_and_partition_vs_B3_conditional':(c['T']-c['certificates']-c['partition'])/base['T']})
    comparisons=[]
    for label in ['C1_ORIGINAL','C1_NO_CERT_I01','B2_RESERVE_EXACT_I01','B3_ALL_SCORES_I01']:
        block_logs=[statistics.mean(math.log(workers[case,b,'C1_I01']['T']/workers[case,b,label]['T']) for case in ['T100_SOC_25','T100_SOC_27']) for b in range(1,21)]
        point=math.exp(statistics.mean(block_logs));original=next(x for x in read(O/'I01_analysis.json')['equal_case_aggregate'] if x['baseline']==label)
        assert abs(point-original['ratio'])<1e-12
        comparisons.append({'baseline':label,'ratio':point,'reproduced_from_raw':True,'minimum_complete_block_ratio':math.exp(min(block_logs)),'maximum_complete_block_ratio':math.exp(max(block_logs))})
    candidate_only=.9/floor
    result={'version':'A-E02-budget-reassessment-1.0','policy_sha256':sha(A/'reassessment_policy.json'),'source_index_sha256':sha(O/'runs.jsonl'),
        'headroom_runs':42,'paired_C1_runs':40,'aggregate_floor':floor,'conditional_maximum_saving':1-floor,
        'families':families,'symmetric_common_cost_scenarios':grids,
        'asymmetric_vs_symmetric':{'candidate_only_uniform_nonengine_reduction_with_free_engine':1-candidate_only,
            'same_reduction_given_to_B3_ratio':ratio(head,candidate_only,0),
            'distinction':'3.52% algebra from E07 is an exclusive candidate-side assumption. If the same common optimization goes to B3, it is not sufficient. Original E07 arithmetic is not retracted.'},
        'comparisons_reproduced':comparisons,
        'optimistic_removal_aggregate':{k:gm([x[k] for x in paired]) for k in ['C1_vs_B3','no_certificate_vs_B3_measured','free_certificates_and_partition_vs_B3_conditional']},
        'per_case_optimistic_removal':[{'case':case,**{k:gm([x[k] for x in paired if x['case']==case]) for k in ['C1_vs_B3','no_certificate_vs_B3_measured','free_certificates_and_partition_vs_B3_conditional']}} for case in ['T100_SOC_25','T100_SOC_27']],
        'limitations':['Counterfactuals keep other costs fixed, cannot predict changed implementations, batching, concurrency or operating domains.','Three headroom blocks are descriptive; no new confidence/novelty theorem.','Local primary sources and tests do not establish exhaustive priority.','No new method/scoring/model inference or validation/final evaluation executed.'],
        'new_E03_started':False,'new_speed_runs':0,'validation_accessed':False,'final_holdout_accessed':False}
    save(E/'budget_analysis.json',result);save(E/'budget_inputs.json',{'worker_sha256':hashes,'raw_components':details,'paired_counterfactuals':paired,'script_sha256':sha(Path(__file__))})
    print(json.dumps({'floor':floor,'shared_reductions':[(x['candidate_engine_fraction_of_B3'],x['required_shared_nonengine_reduction']) for x in grids],'optimistic':result['optimistic_removal_aggregate'],'families_with_opportunity':[(x['case'],x['required_engine_reduction_if_possible']) for x in families if x['max_residual_engine_fraction_for_own_10_percent'] is not None]}))
if __name__=='__main__':main()
