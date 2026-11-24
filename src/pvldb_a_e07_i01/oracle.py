"""Independent full-snapshot oracle. Deliberately imports no engine/model/bound code."""
from datetime import date
import math

def exact(documents,query,corpus_version):
    p=len(query['vector']);q=[float(x) for x in query['vector']]
    if not p or not all(math.isfinite(x) for x in q) or abs(math.fsum(x*x for x in q)-1)>1e-12:raise ValueError('invalid_vector')
    if type(query['k']) is not int or query['k']<1:raise ValueError('invalid_k')
    when=date.fromisoformat(query['query_time']);seen=set();answers=[]
    for d in documents:
        if d['doc_id'] in seen:raise ValueError('duplicate_doc_id')
        seen.add(d['doc_id']);frags=set();scored=[]
        for f in d['fragments']:
            if f['fragment_id'] in frags:raise ValueError('duplicate_fragment_id')
            frags.add(f['fragment_id']);v=[float(x) for x in f['vector']]
            if len(v)!=p or not all(math.isfinite(x) for x in v) or abs(math.fsum(x*x for x in v)-1)>1e-12:raise ValueError('invalid_vector')
            score=math.fsum(q[j]*v[j] for j in range(p))
            scored.append((score,f))
        m=d['metadata']
        if m.get('enabled') is not True or any(k not in m for k in ['valid_from','valid_to']):continue
        if any(k not in m or m[k]!=v for k,v in query['filter'].items()):continue
        if not date.fromisoformat(m['valid_from'])<=when<date.fromisoformat(m['valid_to']):continue
        if not scored:continue
        best=sorted(scored,key=lambda pair:(-pair[0],pair[1]['fragment_id'].encode('utf8')))[0]
        answers.append((best[0],d['doc_id'],best[1]['fragment_id'],best[1]['text_version']))
    result=sorted(answers,key=lambda row:(-row[0],row[1].encode('utf8')))[:query['k']]
    return {'query_id':query['query_id'],'query_version':query['query_version'],'config_version':query['config_version'],
        'corpus_version':corpus_version,'ordered_hits':[[d,f,v] for s,d,f,v in result]}
