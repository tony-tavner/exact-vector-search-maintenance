#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only recomputation of the reported numbers from the bundled run records; no inference or network.

Run reproduction/unpack_archives.py first. Usage: python3 reproduction/reproduce_results.py [--output NEW_FILE.json]
"""
import argparse
import collections
import hashlib
import json
import math
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
SOURCE = PACKAGE  # repository root after reproduction/unpack_archives.py
# Files whose local machine paths were replaced by placeholders: published hash -> hash recorded at measurement time.
REDACTED = {r['path']: r for r in json.loads((PACKAGE / 'archives' / 'redactions.json').read_text(encoding='utf-8'))['files']}
matched_through_redaction_map = 0


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load(path):
    return json.loads((SOURCE / path).read_text(encoding='utf-8'))


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def gm(values):
    values = list(values)
    require(bool(values) and all(v > 0 for v in values), 'Invalid geometric mean input')
    return math.exp(math.fsum(math.log(v) for v in values) / len(values))


def close(a, b, label):
    require(abs(a - b) < 2e-13, 'Recomputed value differs: ' + label)


def recorded_hash_matches(path, recorded):
    global matched_through_redaction_map
    actual = sha(path)
    if actual == recorded:
        return True
    entry = REDACTED.get(path.relative_to(SOURCE).as_posix())
    if entry is not None and entry['original_sha256'] == recorded and entry['sha256'] == actual:
        matched_through_redaction_map += 1
        return True
    return False


def checked_worker(row):
    folder = SOURCE / row['path']
    for name, key in [('worker.json', 'worker_sha256'), ('validation.json', 'validation_sha256')]:
        require(recorded_hash_matches(folder / name, row[key]), 'Hash mismatch: ' + str(folder / name))
    worker = json.loads((folder / 'worker.json').read_text(encoding='utf-8'))
    require(row['status'] == 'completed' and row['correct'], 'Incomplete or incorrect worker')
    require(worker['T_total_ns'] == row['T_total_ns'], 'Worker/index total mismatch')
    return worker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.output is not None:
        require(not args.output.exists(), 'Output must be a new file')
    cases = ['P01_cold_local_11', 'P02_cold_mass_15']
    baselines = ['B0_FULL_EXACT', 'B1_DELTA_MATRIX', 'B2_RESERVE_EXACT', 'B3_ALL_SCORES',
                 'B4_SIMPFER_EXACT', 'B5_SIMPFERPP_EXACT', 'B6_HYBRID_EXACT']
    index = [json.loads(line) for line in (SOURCE / 'results/pilot_runs.jsonl').read_text(encoding='utf-8').splitlines()]
    selected = [r for r in index if r['phase'] == 'measured' and r['case_id'] in cases and r['method'] in ['C1'] + baselines]
    require(len(selected) == 640, 'Expected 640 E05 measurements')
    data = {}
    for row in selected:
        worker = checked_worker(row)
        require(row['mode'] == 'cold' and worker['embedding_calls'], 'Cold embeddings absent')
        require(all(c['exit_code'] == 0 for c in worker['embedding_calls']), 'Failed embedding call')
        key = row['case_id'], row['block'], row['method']
        require(key not in data, 'Duplicate E05 observation')
        data[key] = row['T_total_ns']
    precision = load('reports/e_stages/E05/E05_2026-11-18_01/precision_final.json')['contrasts']
    e05 = []
    for baseline in baselines:
        ratio = gm(gm(data[(case, block, 'C1')] / data[(case, block, baseline)] for case in cases)
                   for block in range(1, 41))
        original = precision['cold_equal_history/' + baseline]
        close(ratio, original['ratio'], baseline)
        e05.append({'baseline': baseline, 'ratio': ratio, 'time_reduction_percent': 100 * (1-ratio),
                    'speedup': 1/ratio, 'central_95_low': original['central_95_low'],
                    'central_95_high': original['central_95_high'],
                    'simultaneous_one_sided_upper': original['one_sided_bonferroni_upper'],
                    'paired_blocks_per_history': 40,
                    'per_history_ratio': {case: gm(data[(case, k, 'C1')] / data[(case, k, baseline)] for k in range(1,41)) for case in cases}})
    e07_index = [json.loads(line) for line in (SOURCE / 'results/iterations/E07_2026-11-18_01/runs.jsonl').read_text(encoding='utf-8').splitlines()]
    e07_cases = ['T100_SOC_25', 'T100_SOC_27']
    i01_rows = [r for r in e07_index if r['phase'] == 'I01' and not r['warmup']]
    i01_data = {}
    verified_i01 = 0
    for row in i01_rows:
        if row['status'] != 'completed':
            continue
        checked_worker(row)
        key = row['case_id'], row['block'], row['label']
        require(key not in i01_data, 'Duplicate I01 observation')
        i01_data[key] = row['T_total_ns']
        verified_i01 += 1
    published_i01 = load('results/iterations/E07_2026-11-18_01/I01_analysis.json')['equal_case_aggregate']
    i01 = []
    for original in published_i01:
        baseline = original['baseline']
        record = dict(original)
        if original['estimable']:
            blocks = sorted(set(r['block'] for r in i01_rows if r['label'] == baseline))
            require(len(blocks) == original['blocks'], 'Unexpected block count for ' + baseline)
            ratios = []
            for block in blocks:
                pairs = [(i01_data.get((case, block, 'C1_I01')), i01_data.get((case, block, baseline))) for case in e07_cases]
                require(all(a is not None and b is not None for a,b in pairs), 'Missing paired I01 run')
                ratios.append(gm(a/b for a,b in pairs))
            ratio = gm(ratios)
            close(ratio, original['ratio'], baseline)
            record['ratio_recomputed'] = ratio
            record['time_reduction_percent'] = 100 * (1-ratio)
        i01.append(record)
    budget = load('reports/e_stages/E02/E02_2026-11-18_04/budget_reassessment.json')
    headroom_lookup = {r['path'] + '/worker.json': r for r in e07_index if r['phase'] == 'headroom' and not r['warmup']}
    ratios, headroom_records = [], []
    for record in budget['records']:
        row = headroom_lookup[record['worker']]
        worker = checked_worker(row)
        engine_ns = sum(s['end_ns'] - s['start_ns'] for s in worker['metrics']['spans']
                        if s['name'] in ('initialization', 'maintenance'))
        require(engine_ns == record['engine_ns'] and worker['T_total_ns'] == record['total_ns'], 'Budget span mismatch')
        ratio = 1 - engine_ns / worker['T_total_ns']
        ratios.append(ratio)
        headroom_records.append({'case': record['case'], 'block': row['block'],
                                 'worker': record['worker'], 'total_ns': worker['T_total_ns'],
                                 'engine_ns': engine_ns, 'residual_ratio': ratio})
    require(len(ratios) == 42 and len(set(r['case'] for r in headroom_records)) == 14, 'Headroom panel changed')
    floor = gm(ratios)
    close(floor, budget['floors']['free_engine'], 'free_engine budget')
    answers = sum(r['query_outputs'] for r in selected if r['method'] == 'C1')
    require(answers == 2720, 'Unexpected C1 cold answer count')
    result = {
        'id': 'pvldb2027_paper_A_recomputed_results',
        'source': 'Bundled immutable worker/index records', 'new_experiment': False, 'network_used': False,
        'intervals': 'Copied from the preserved precision/analysis records; bootstrap not rerun; fixed-workload timing uncertainty only',
        'E05': {'histories': cases, 'methods': 8, 'measured_records_verified': len(selected),
                'worker_validation_hashes_verified': len(selected)*2, 'C1_full_answers': answers,
                'C1_mismatches': 0, 'contrasts': e05},
        'E07_I01': {'histories': e07_cases, 'completed_workers_verified': verified_i01,
                    'measured_status_counts': dict(collections.Counter(r['status'] for r in i01_rows)),
                    'contrasts': i01},
        'headroom': {'records': headroom_records, 'runs': 42, 'families': 14, 'residual_total_ratio': floor,
                     'conditional_saving_percent': 100*(1-floor),
                     'assumption': 'Engine construction and maintenance are free; other observed costs fixed',
                     'measured_new_method': False},
        'record_hashes_matched_through_redaction_map': matched_through_redaction_map,
        'original_all_baseline_ten_percent_goal_achieved': False,
        'independent_replication': False}
    text = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output is None:
        print(text, end='')
    else:
        with args.output.open('x', encoding='utf-8') as stream:
            stream.write(text)
        print(json.dumps({'output': str(args.output), 'E05_records_verified': len(selected),
                          'E07_completed_records_verified': verified_i01, 'headroom_records_verified': len(ratios),
                          'passed': True}, ensure_ascii=False))


if __name__ == '__main__':
    main()
