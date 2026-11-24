"""Independent full-snapshot oracle for hand-authored E01 answers."""
import argparse
from datetime import date
import hashlib
import json
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def vector(v,dimension):
    try:v=[float(x) for x in v]
    except (TypeError,ValueError):raise ValueError('invalid_vector')
    if len(v)!=dimension or not all(math.isfinite(x) for x in v):raise ValueError('invalid_vector')
    norm=math.fsum(x*x for x in v)
    if norm==0 or abs(norm-1)>1e-12:raise ValueError('invalid_vector')
    return v

def exact(documents,q,corpus_version):
    if not isinstance(q['k'],int) or isinstance(q['k'],bool) or q['k']<=0:raise ValueError('invalid_k')
    query=vector(q['vector'],len(q['vector']));today=date.fromisoformat(q['query_time'])
    ids=[d['doc_id'] for d in documents]
    if len(ids)!=len(set(ids)):raise ValueError('duplicate_doc_id')
    rows=[]
    for d in documents:
        candidates=[];seen=set()
        for f in d['fragments']:
            if f['fragment_id'] in seen:raise ValueError('duplicate_fragment_id')
            seen.add(f['fragment_id']);v=vector(f['vector'],len(query))
            score=math.fsum(a*b for a,b in zip(query,v))
            candidates.append((-score,f['fragment_id'].encode('utf-8'),f))
        m=d['metadata']
        required=['enabled','valid_from','valid_to']+list(q['filter'])
        if any(x not in m for x in required):continue
        if m['enabled'] is not True:continue
        if any(m[key]!=value for key,value in q['filter'].items()):continue
        if not(date.fromisoformat(m['valid_from'])<=today<date.fromisoformat(m['valid_to'])):continue
        if not candidates:continue
        winner=min(candidates,key=lambda x:x[:2]);f=winner[2]
        rows.append((winner[0],d['doc_id'].encode('utf-8'),[d['doc_id'],f['fragment_id'],f['text_version']]))
    hits=[x[2] for x in sorted(rows,key=lambda x:x[:2])[:q['k']]]
    return {'query_id':q['query_id'],'query_version':q['query_version'],'config_version':q['config_version'],
            'corpus_version':corpus_version,'ordered_hits':hits}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True);args=ap.parse_args()
    path=ROOT/'tests/fixtures/e01_contract_v1.json';obj=json.loads(path.read_text());results=[]
    for c in obj['cases']:
        for side in ['before','after']:
            snap=c[side];answer=exact(snap['documents'],c['query'],snap['corpus_version'])
            assert answer['ordered_hits']==c['expected_'+side],(c['id'],side,answer)
            results.append({'case':c['id'],'snapshot':side,'passed':True,'answer':answer})
        if c['id']=='new_leader_old_sources_unchanged':
            assert c['before']['documents']==c['after']['documents'][:len(c['before']['documents'])]
    invalid=[]
    for c in obj['invalid_cases']:
        try:exact(c['documents'],c['query'],'invalid')
        except ValueError as e:
            assert str(e)==c['expected_error'];invalid.append({'case':c['id'],'passed':True,'error':str(e)})
        else:raise AssertionError('Invalid vector accepted: '+c['id'])
    report={'passed':True,'valid_cases':len(obj['cases']),'snapshots':len(results),'invalid_cases':len(invalid),
            'fixture_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'scope':'Full-snapshot toy operator vs handwritten expected answers; no proposed incremental method, no performance comparison.',
            'results':results,'invalid_results':invalid}
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['results','invalid_results']}))

if __name__=='__main__':main()
