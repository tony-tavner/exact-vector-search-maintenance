#!/usr/bin/env python3
"""Freeze development-only pilot v1 before measuring performance."""
import copy, json, math, os
from pathlib import Path
os.environ.update({k: '1' for k in ['OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS']})
import numpy as np
from e05_common import ROOT, dump_new, sha, snapshot_answers, replay_events, expected_trace

OUT = ROOT / 'results/pilot/E05_2026-11-18_01'
DATA = ROOT / 'data/processed/onet29_3_v1'

def main():
    OUT.mkdir(parents=True, exist_ok=False)
    index = [json.loads(x) for x in (DATA / 'embeddings_development/index.jsonl').read_text().splitlines()]
    assert all(x['split'] == 'development' for x in index)
    arr = np.load(DATA / 'embeddings_development/vectors.npy', allow_pickle=False)
    vectors = {x['id']: arr[x['row']].tolist() for x in index}
    docs = [json.loads(x) for x in (DATA / 'documents.jsonl').read_text().splitlines() if json.loads(x)['split'] == 'development']
    queries = [json.loads(x) for x in (DATA / 'queries.jsonl').read_text().splitlines() if json.loads(x)['split'] == 'development']
    split = json.loads((ROOT / 'data/splits.json').read_text())
    assert all(d['doc_id'] in split['documents']['development'] for d in docs)
    for d in docs:
        for f in d['fragments']: f['vector'] = vectors[f['fragment_id']]
    for q in queries: q['vector'] = vectors[q['query_id']]
    cases = []

    def make(cid, ds, qs, k, filter_mode='role'):
        w = {'schema_version': 1, 'case_id': cid, 'split': 'development', 'mode': 'ready_vectors',
             'provenance': 'O*NET 29.3 development text; controlled artificial events and applicability; no semantic gold',
             'corpus_version': cid + ':0', 'documents': copy.deepcopy(ds), 'queries': copy.deepcopy(qs),
             'batches': [], 'parameters': {'leaf_limit': 64}}
        for i, q in enumerate(w['queries']):
            q['k'] = k; q['query_version'] = 'E05-v1:' + cid
            if filter_mode == 'broad': q['filter'] = {}
            if filter_mode == 'bucket': q['filter'] = {'pilot_bucket': i % 4}
        if filter_mode == 'bucket':
            for i, d in enumerate(w['documents']): d['metadata']['pilot_bucket'] = i % 4
        return w

    def add(w, events, label):
        w['batches'].append({'corpus_version': w['case_id'] + ':' + str(len(w['batches']) + 1),
                             'event_label': label, 'events': copy.deepcopy(events)})

    def version_fragment(doc, source, step, pos=0):
        f = copy.deepcopy(doc['fragments'][pos]); f['text_version'] = 'E05:v' + str(step)
        f['text'] = source['text']; f['vector'] = source['vector']
        return {'op': 'put_fragment', 'doc_id': doc['doc_id'], 'fragment': f}

    d11 = [d for d in docs if d['occupation_family'] == '11']
    q11 = [q for q in queries if q['occupation_family'] == '11']
    d15 = [d for d in docs if d['occupation_family'] == '15']
    q15 = [q for q in queries if q['occupation_family'] == '15']

    # Best available document for q0 is deliberately withheld then inserted.
    pool = d11[:13]; q = copy.deepcopy(q11[0]); q['k'] = 1
    lead_hit = snapshot_answers(pool, [q], 'selection')[q['query_id']]['ordered_hits'][0]
    leader = next(d for d in pool if d['doc_id'] == lead_hit[0])
    initial = [d for d in pool if d['doc_id'] != leader['doc_id']]
    w = make('P01_cold_local_11', initial, q11[:4], 5); state = copy.deepcopy(w['documents'])
    event_sets = [([{'op': 'put_document', 'document': leader}], 'insert_withheld_leader'),
                  ([{'op': 'delete_fragment', 'doc_id': leader['doc_id'], 'fragment_id': lead_hit[1]}], 'delete_winning_fragment')]
    for events, label in event_sets: add(w, events, label); state = replay_events(state, events)
    for step in range(3, 9):
        d = state[step % len(state)]
        if not d['fragments']: d = next(x for x in state if x['fragments'])
        if step in (5, 6):
            target = initial[0]['doc_id']
            events = [{'op': 'metadata', 'doc_id': target, 'changes': {'enabled': step == 6}}]
            label = 'applicability_disable' if step == 5 else 'applicability_restore'
        else:
            src = d['fragments'][0] if step == 4 else initial[(step + 1) % len(initial)]['fragments'][0]
            events = [version_fragment(d, src, step)]
            label = 'text_version_only' if step == 4 else 'fragment_replacement'
            if step == 7:
                events.append({'op': 'metadata', 'doc_id': initial[1]['doc_id'], 'changes': {'enabled': False}})
                label = 'mixed_atomic_batch'
        add(w, events, label); state = replay_events(state, events)
    local_ready = copy.deepcopy(w); local_ready['case_id'] = 'P03_ready_local_11'
    # Versions stay identical across cold/ready diagnostic twins; numeric input source differs.
    w['mode'] = 'cold'; cases.append((w, 'primary_cold', 20, 120, 16 * 1024**3))

    w = make('P02_cold_mass_15', d15[:20], q15[:8], 10, 'broad'); state = copy.deepcopy(w['documents'])
    for step, fraction in [(1, .2), (2, 1.0)]:
        count = round(len(state) * fraction); events = []
        for i, d in enumerate(state[:count]):
            other = state[(i + 1) % len(state)]
            for j in range(len(d['fragments'])):
                events.append(version_fragment(d, other['fragments'][j % len(other['fragments'])], step, j))
        add(w, events, 'replace_20_percent' if step == 1 else 'replace_100_percent')
        state = replay_events(state, events)
    add(w, [{'op': 'metadata', 'doc_id': d['doc_id'], 'changes': {'enabled': i % 2 == 0}} for i, d in enumerate(state)], 'mass_applicability_100_percent')
    mass_ready = copy.deepcopy(w); mass_ready['case_id'] = 'P04_ready_mass_15'
    w['mode'] = 'cold'; cases.append((w, 'primary_cold', 20, 120, 16 * 1024**3))
    cases += [(local_ready, 'secondary_ready', 20, 120, 16 * 1024**3), (mass_ready, 'secondary_ready', 20, 120, 16 * 1024**3)]

    # A declared favorable shape selected by algebraic margin, never by timing.
    w = make('P05_ready_dominated_11', d11[:16], q11[:1], 5)
    q = w['queries'][0]; chosen = None
    for d in w['documents']:
        fs = sorted(d['fragments'], key=lambda f: f['fragment_id'].encode())
        if len(fs) < 2: continue
        def score(f): return math.fsum(x*y for x,y in zip(q['vector'],f['vector']))
        # The witness is min(S), not min(all fragments): either original
        # fragment may be changed, leaving the other as the only survivor.
        for witness, changed in [(fs[0], fs[1]), (fs[1], fs[0])]:
            lower = next((f for source in d11[:16] for f in source['fragments'] if f['text'] != changed['text'] and score(f) < score(witness) - .02), None)
            if lower and score(changed) < score(witness) - .02:
                chosen = (d, changed, lower); break
        if chosen: break
    if chosen is None: raise RuntimeError('No declared favorable development witness; record missing case, do not fabricate vectors')
    d, original, lower = chosen
    for step in range(1, 21):
        f = copy.deepcopy(original); src = lower if step % 2 else original
        f.update(text=src['text'], vector=src['vector'], text_version='E05:dominated:' + str(step))
        add(w, [{'op': 'put_fragment', 'doc_id': d['doc_id'], 'fragment': f}], 'nonwinning_fragment_alternation')
    cases.append((w, 'mechanism_ready', 20, 120, 16 * 1024**3))

    w = make('P06_ready_selective_15', d15[:32], q15[:16], 20, 'bucket'); state = copy.deepcopy(w['documents'])
    for step, count in [(1, 1), (2, 6), (3, 32)]:
        events = [{'op': 'metadata', 'doc_id': d['doc_id'], 'changes': {'pilot_bucket': (i + step) % 4}} for i, d in enumerate(state[:count])]
        add(w, events, 'controlled_filter_changes_' + str(count)); state = replay_events(state, events)
    cases.append((w, 'secondary_ready', 20, 120, 16 * 1024**3))

    w = make('P07_ready_scale_128', docs[:128], queries[:32], 20, 'broad'); state = copy.deepcopy(w['documents'])
    for step, count in [(1, 1), (2, 26), (3, 128)]:
        events = [version_fragment(d, state[(i + 1) % len(state)]['fragments'][0], step) for i, d in enumerate(state[:count])]
        add(w, events, 'replace_' + str(count) + '_of_128'); state = replay_events(state, events)
    cases.append((w, 'scale_ready', 20, 30, 16 * 1024**3))

    w = make('P08_memory_headroom_256', docs[:256], queries[:64], 20, 'broad')
    add(w, [version_fragment(d, w['documents'][(i + 1) % 256]['fragments'][0], 1) for i, d in enumerate(w['documents'][:51])], 'replace_51_of_256')
    cases.append((w, 'diagnostic_memory_limit', 3, 30, 128 * 1024**2))

    mandatory = json.loads((ROOT / 'docs/success_criteria.json').read_text())['baselines']['mandatory_exact']
    methods = ['C1'] + mandatory + ['B2_ADAPTIVE']; records = []
    for w, role, repeats, timeout, memory in cases:
        if w['mode'] == 'cold':
            def remove_vectors(x):
                if isinstance(x, dict):
                    x.pop('vector', None)
                    for value in x.values(): remove_vectors(value)
                elif isinstance(x, list):
                    for value in x: remove_vectors(value)
            remove_vectors(w)
        path = OUT / 'workloads' / (w['case_id'] + '.json'); dump_new(path, w)
        ms = methods + (['C1_FLAT', 'C1_SEPARATE', 'C1_MARGIN', 'C1_NO_CERT'] if role == 'mechanism_ready' else [])
        records.append({'id': w['case_id'], 'path': str(path.relative_to(ROOT)), 'sha256': sha(path), 'role': role,
                        'mode': w['mode'], 'documents': len(w['documents']), 'fragments': sum(len(d['fragments']) for d in w['documents']),
                        'queries': len(w['queries']), 'k': sorted({q['k'] for q in w['queries']}), 'batches': len(w['batches']),
                        'families': sorted({d['occupation_family'] for d in w['documents']}), 'methods': ms,
                        'timing_blocks': repeats, 'timeout_seconds': timeout, 'max_rss_bytes': memory})
    protocol = {'version': 'A-E05-pilot-1.0', 'attempt_id': 'E05_2026-11-18_01', 'stage_id': 'E05',
                'frozen_before_timing': True, 'implementation_version': 'A-E04-0.1', 'E06_started': False,
                'split': 'development_only', 'holdout_retrieval_used': False, 'validation_split_used': False,
                'primary_domain_is_confirmatory': False, 'cases': records, 'mandatory_methods': mandatory,
                'method_parameters': 'Accepted E04 defaults; leaf_limit=64, fixed reserve=2k, B2 adaptive and B6 fraction=.3 untuned.',
                'warmup': 'One complete excluded block of every case/method, with fresh worker and physical cold embeddings; retained as warmup.',
                'cold_definition': 'No cross-run embedding-result reuse. OS file/model page cache is NOT flushed; warm-system cold-vector preparation, not machine-boot cold.',
                'repeat_rule': {'initial_complete_blocks': 20, 'extension_complete_blocks': 20, 'maximum_complete_blocks': 40,
                    'trigger': 'At 20 only: any primary cold C1/mandatory ratio central 95% bootstrap relative halfwidth > .05 -> add 20 complete blocks of ALL non-resource cases; no effect/p-value stopping.',
                    'if_still_imprecise': 'Keep full results; precision inconclusive. Do not relax effect target or claim superiority.',
                    'resource_case_blocks': 3, 'resource_reason': '128 MiB diagnostic headroom limit, not the 16 GiB article constraint; no speed ratio from killed runs.'},
                'order': {'seed': 18051801, 'design': 'Random case order and independent randomized method order inside each paired complete block; sequential child workers only.'},
                'uncertainty': {'bootstrap_replicates': 10000, 'seed': 18051802, 'unit': 'complete paired timing block',
                    'scope': 'Conditional measurement uncertainty for this small diagnostic suite only; no population/final claims.',
                    'cold_aggregate': 'Equal weight to the two predeclared cold histories, each from a different development SOC family; different settings, not final full-family estimand.',
                    'report_casewise': True, 'simultaneous_one_sided_alpha': .05, 'mandatory_contrasts': 7,
                    'pilot_precision_relative_halfwidth': .05, 'effect_target_unchanged_ratio': .90},
                'correctness': 'All full answers from every completed run, independent raw-snapshot oracle; cold vectors reconstructed from saved physical raw inference outputs; exact versions/order, no epsilon.',
                'failure_policy': 'Retain stdout/stderr/supervisor/outcome. Output mismatch or numeric input non-repeatability stops suite with rework; timeout/memory limits are censored outcomes, never infinite speedups.',
                'cost_policy': 'Unchanged run_pilot.py direct worker T_total, embeddings/build/update/reads/serialization included; independent validator excluded. Nested spans descriptive only.',
                'memory_policy': 'Sampled tree RSS lower bound; self+single sequential child high-water upper bound. Final memory criterion not certified from sampled RSS.',
                'noise_policy': 'Fresh process, identical thread limits, interleaved blocks, excluded warmup; log load average/thermal state/top process names before every run. No overlapping article benchmark launched.',
                'limits': ['Own exact-contract baseline adaptations, not original author binaries', 'No semantic gold, Recall_changed_at_k=NA', 'No actual 1e5/1e6 fragment run; extrapolate cautiously from measured counts/costs', 'No final baseline/parameter selection in E05'],
                'input_sha256': {f: sha(ROOT / f) for f in ['docs/success_criteria.json', 'data/splits.json', 'environment/manifest.json',
                    'validation/implementation_report.json', 'scripts/run_pilot.py', 'scripts/prepare_e05_pilot.py', 'scripts/e05_common.py']}}
    dump_new(ROOT / 'protocol/pilot_v1.json', protocol)
    print(json.dumps({'cases': len(records), 'planned_initial_measured_runs': sum(len(x['methods']) * x['timing_blocks'] for x in records),
                      'cold_cases': 2, 'E06_started': False}))

if __name__ == '__main__': main()
