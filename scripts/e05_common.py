"""Independent E05 workload replay and validation. No engine pruning imports."""
import copy, hashlib, json, math, struct, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from pvldb_a.oracle import exact

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()

def dump_new(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')

def replay_events(documents, events):
    docs = {d['doc_id']: copy.deepcopy(d) for d in documents}
    for event in events:
        op = event['op']; did = event.get('doc_id')
        if op == 'put_document':
            d = copy.deepcopy(event['document']); docs[d['doc_id']] = d
        elif op == 'delete_document':
            del docs[did]
        elif op == 'metadata':
            docs[did]['metadata'].update(event['changes'])
        elif op == 'put_fragment':
            f = copy.deepcopy(event['fragment'])
            docs[did]['fragments'] = [x for x in docs[did]['fragments'] if x['fragment_id'] != f['fragment_id']] + [f]
        elif op == 'delete_fragment':
            old = docs[did]['fragments']
            docs[did]['fragments'] = [f for f in old if f['fragment_id'] != event['fragment_id']]
            assert len(old) == len(docs[did]['fragments']) + 1
        else:
            raise ValueError(op)
    return list(docs.values())

def snapshot_answers(documents, queries, version):
    return {q['query_id']: exact(documents, q, version) for q in queries}

def expected_trace(workload):
    docs = copy.deepcopy(workload['documents']); qs = copy.deepcopy(workload['queries'])
    answers = [snapshot_answers(docs, qs, workload['corpus_version'])]; trace = []
    for batch in workload['batches']:
        old_docs = {d['doc_id']: d for d in docs}; old_qs = qs
        changed = {e['document']['doc_id'] if e['op'] == 'put_document' else e['doc_id'] for e in batch['events']}
        docs = replay_events(docs, batch['events'])
        if batch.get('documents') is not None: docs = copy.deepcopy(batch['documents'])
        if batch.get('queries') is not None: qs = copy.deepcopy(batch['queries'])
        new = snapshot_answers(docs, qs, batch['corpus_version']); new_docs = {d['doc_id']: d for d in docs}
        # Ignore the obligatory corpus_version change when measuring affected hits.
        affected = sum(q not in answers[-1] or new[q]['ordered_hits'] != answers[-1][q]['ordered_hits'] for q in new)
        old_fragments = sum(len(d['fragments']) for d in old_docs.values())
        changed_fragments = 0
        for did in changed:
            old = {f['fragment_id']: f for f in old_docs.get(did, {}).get('fragments', [])}
            after = {f['fragment_id']: f for f in new_docs.get(did, {}).get('fragments', [])}
            changed_fragments += sum(old.get(fid) != after.get(fid) for fid in old.keys() | after.keys())
        applicability = []
        for q in old_qs:
            count = sum(d['metadata'].get('enabled') is True and
                        d['metadata'].get('valid_from', '9999') <= q['query_time'] < d['metadata'].get('valid_to', '') and
                        all(d['metadata'].get(k) == v for k, v in q['filter'].items()) for d in old_docs.values())
            applicability.append(count)
        trace.append({'version': batch['corpus_version'], 'event_label': batch.get('event_label'),
                      'old_document_count': len(old_docs), 'old_fragment_count': old_fragments,
                      'changed_documents': len(changed), 'changed_document_fraction': len(changed) / max(1, len(old_docs)),
                      'changed_fragments': changed_fragments, 'changed_fragment_fraction': changed_fragments / max(1, old_fragments),
                      'affected_hit_outputs': affected, 'query_outputs': len(new),
                      'affected_hit_fraction': affected / max(1, len(new)),
                      'applicable_documents_per_query_before': applicability})
        answers.append(new)
    return answers, trace

def cold_vectors(run):
    """Reconstruct the vectors independently from saved physical inference outputs."""
    cache = {}
    for folder in sorted((Path(run) / 'embedding').glob('call_*')):
        inputs = (folder / 'input.txt').read_text().splitlines()
        values = json.loads((folder / 'raw.json').read_text())['data']
        assert len(inputs) == len(values)
        for i, (text, entry) in enumerate(zip(inputs, values)):
            assert entry['index'] == i
            if text.startswith('search_query: '): key = ('query', text[len('search_query: '):])
            else:
                assert text.startswith('search_document: ')
                key = ('document', text[len('search_document: '):])
            v = [float(x) for x in entry['embedding']]
            assert len(v) == 768 and all(math.isfinite(x) for x in v)
            norm = math.sqrt(math.fsum(x * x for x in v)); assert norm > 0
            cache[key] = tuple(x / norm for x in v)
    h = hashlib.sha256()
    for key in sorted(cache):
        h.update(json.dumps(key, ensure_ascii=False).encode('utf8'))
        h.update(struct.pack('=' + str(len(cache[key])) + 'd', *cache[key]))
    return cache, h.hexdigest()

def prepared_workload(workload, cache):
    result = copy.deepcopy(workload)
    def document(d):
        for f in d['fragments']: f['vector'] = list(cache['document', f['text']])
    def query(q): q['vector'] = list(cache['query', q['query_text']])
    for d in result['documents']: document(d)
    for q in result['queries']: query(q)
    for b in result['batches']:
        for d in b.get('documents') or []: document(d)
        for q in b.get('queries') or []: query(q)
        for e in b['events']:
            if e['op'] == 'put_document': document(e['document'])
            elif e['op'] == 'put_fragment': e['fragment']['vector'] = list(cache['document', e['fragment']['text']])
    return result
