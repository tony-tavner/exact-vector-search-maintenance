"""Paired complete-block timing uncertainty; no population inference."""
import math
import numpy as np

def interval(log_ratios, seed=18051802, draws=10000):
    x = np.asarray(log_ratios, dtype=float)
    if len(x) < 2: return {'estimable': False, 'blocks': len(x)}
    rng = np.random.default_rng(seed)
    means = x[rng.integers(0, len(x), size=(draws, len(x)))].mean(axis=1)
    estimate = float(np.exp(x.mean())); low, high = np.exp(np.quantile(means, [.025, .975]))
    upper = float(np.exp(np.quantile(means, 1 - .05 / 7)))
    return {'estimable': True, 'blocks': len(x), 'ratio': estimate,
            'central_95_low': float(low), 'central_95_high': float(high),
            'relative_halfwidth': float((high-low)/(2*estimate)),
            'one_sided_bonferroni_upper': upper, 'minimum_log_ratio': float(x.min()),
            'maximum_log_ratio': float(x.max()), 'log_ratio_sd': float(x.std(ddof=1)),
            'scope': 'Timing-block uncertainty conditional on this fixed pilot suite'}

def precision(records, protocol, blocks):
    rows = {(r['block'], r['case_id'], r['method']): r for r in records if r['phase'] == 'measured'}
    cases = [c for c in protocol['cases'] if c['role'] == 'primary_cold']
    methods = ['C1'] + protocol['mandatory_methods']; complete = []
    for b in range(1, blocks + 1):
        if all(rows.get((b,c['id'],m),{}).get('status') == 'completed' for c in cases for m in methods): complete.append(b)
    results = {}; all_precise = len(complete) == blocks
    for bi, method in enumerate(protocol['mandatory_methods']):
        case_logs = []
        for ci, case in enumerate(cases):
            logs = [math.log(rows[b,case['id'],'C1']['T_total_ns']/rows[b,case['id'],method]['T_total_ns']) for b in complete]
            stat = interval(logs, 18051802 + bi * 10 + ci)
            results[case['id'] + '/' + method] = stat; case_logs.append(logs)
            all_precise = all_precise and stat.get('relative_halfwidth', float('inf')) <= .05
        combined = np.mean(np.array(case_logs), axis=0).tolist() if complete else []
        stat = interval(combined, 18051802 + bi * 10 + 9); results['cold_equal_history/' + method] = stat
        all_precise = all_precise and stat.get('relative_halfwidth', float('inf')) <= .05
    return {'blocks_planned': blocks, 'complete_blocks': complete, 'all_primary_precision_met': bool(all_precise),
            'contrasts': results, 'extend_by_preregistered_rule': len(complete) == blocks and not all_precise and blocks == 20,
            'incomplete_primary_suite': len(complete) != blocks}
