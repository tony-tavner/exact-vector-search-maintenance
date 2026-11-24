"""Validated immutable values shared by implementations, not by the oracle."""
from dataclasses import dataclass
from datetime import date
import json,math,struct
from types import MappingProxyType
from . import persistent as avl

def ident(v):
    if type(v) is not str or not v:raise ValueError('invalid_id')
    v.encode('utf-8');return v
def plain(v):
    """Only parsed JSON primitives: no user callbacks in a protected region."""
    t=type(v)
    if t in (str,int,float,bool,type(None)):return
    if t in (list,tuple):
        for item in v:plain(item)
        return
    if t is dict:
        for k,item in v.items():
            if type(k) is not str:raise ValueError('non_json_key')
            plain(item)
        return
    raise ValueError('non_json_value')
def canonical_json(v):
    plain(v)
    return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def vector(values,p=None):
    if type(values) not in (list,tuple) or any(type(x) not in (int,float,str) for x in values):raise ValueError('invalid_vector')
    try:v=tuple(float(x) for x in values)
    except (TypeError,ValueError,OverflowError):raise ValueError('invalid_vector')
    if not v or (p is not None and len(v)!=p) or not all(math.isfinite(x) for x in v):raise ValueError('invalid_vector')
    norm=math.fsum(x*x for x in v)
    if norm==0 or abs(norm-1)>1e-12:raise ValueError('invalid_vector')
    return v,struct.pack('='+str(len(v))+'d',*v)
@dataclass(frozen=True)
class Fragment:
    fid:str;version:str;text:object;v:tuple;bits:bytes;config:str
    @property
    def identity(self):return (self.fid,self.version,self.text,self.bits,self.config)
@dataclass(frozen=True)
class Document:
    did:str;metadata:str;fragments:tuple
@dataclass(frozen=True)
class Query:
    qid:str;version:str;config:str;v:tuple;bits:bytes;k:int;when:str;filters:str
    text:object=None
    @property
    def identity(self):return (self.version,self.config,self.bits,self.k,self.when,self.filters,self.text)
@dataclass(frozen=True)
class Row:
    score:float;did:str;fid:str;version:str
    @property
    def key(self):return (-self.score,self.did.encode('utf-8'))
    @property
    def hit(self):return [self.did,self.fid,self.version]

def query(raw,p=None):
    if type(raw) is not dict:raise ValueError('invalid_query')
    plain(raw)
    k=raw['k']
    if type(k) is not int or k<=0:raise ValueError('invalid_k')
    v,bits=vector(raw['vector'],p)
    if date.fromisoformat(raw['query_time']).isoformat()!=raw['query_time']:raise ValueError('invalid_date')
    if not isinstance(raw['filter'],dict):raise ValueError('invalid_filter')
    text=raw.get('query_text')
    if text is not None:
        if type(text) is not str:raise ValueError('invalid_query_text')
        text.encode('utf8')
    return Query(ident(raw['query_id']),ident(raw['query_version']),ident(raw['config_version']),v,bits,k,raw['query_time'],canonical_json(raw['filter']),text)
def metadata(raw):
    if not isinstance(raw,dict):raise ValueError('invalid_metadata')
    for k in ['valid_from','valid_to']:
        if k in raw and date.fromisoformat(raw[k]).isoformat()!=raw[k]:raise ValueError('invalid_date')
    if 'valid_from' in raw and 'valid_to' in raw and raw['valid_from']>raw['valid_to']:raise ValueError('invalid_interval')
    return canonical_json(raw)
def fragment(raw,p,config):
    if type(raw) is not dict:raise ValueError('invalid_fragment')
    plain(raw)
    if raw.get('config_version',config)!=config:raise ValueError('mixed_config')
    v,bits=vector(raw['vector'],p);text=raw.get('text')
    if text is not None:
        if not isinstance(text,str):raise ValueError('invalid_text')
        text.encode('utf-8')
    return Fragment(ident(raw['fragment_id']),ident(raw['text_version']),text,v,bits,config)
def document(raw,p,config):
    if type(raw) is not dict:raise ValueError('invalid_document')
    plain(raw)
    fs=tuple(fragment(f,p,config) for f in raw['fragments'])
    if len({f.fid for f in fs})!=len(fs):raise ValueError('duplicate_fragment_id')
    return Document(ident(raw['doc_id']),metadata(raw['metadata']),tuple(sorted(fs,key=lambda f:f.fid.encode('utf-8'))))
def applicable(q,d):
    m=json.loads(d.metadata);flt=json.loads(q.filters)
    if m.get('enabled') is not True or 'valid_from' not in m or 'valid_to' not in m:return False
    return all(k in m and m[k]==v for k,v in flt.items()) and m['valid_from']<=q.when<m['valid_to']
def register(ledger,docs,queries,counters):
    for d in docs:
        for f in d.fragments:
            key=('f',d.did,f.fid,f.version,f.config);value=(f.text,f.bits)
            previous=avl.get(ledger,key)
            if previous is not None and previous!=value:raise ValueError('fragment_version_alias')
            ledger=avl.put(ledger,key,value,counters)
    for q in queries:
        key=('q',q.qid,q.version,q.config);previous=avl.get(ledger,key)
        if previous is not None and previous!=q.identity:raise ValueError('query_version_alias')
        ledger=avl.put(ledger,key,q.identity,counters)
    return ledger

def parse_queries(raw):
    if type(raw) not in (list,tuple):raise ValueError('invalid_registry')
    qs=[query(x) for x in raw]
    if len({q.qid for q in qs})!=len(qs):raise ValueError('duplicate_query_id')
    if len({(len(q.v),q.config) for q in qs})>1:raise ValueError('mixed_config_dimension')
    return {q.qid:q for q in qs}
def parse_documents(raw,p,config):
    if type(raw) not in (list,tuple):raise ValueError('invalid_snapshot')
    docs=[document(x,p,config) for x in raw]
    if len({d.did for d in docs})!=len(docs):raise ValueError('duplicate_doc_id')
    return {d.did:d for d in docs}
def events_to_documents(old,events,p,config):
    if type(events) not in (list,tuple):raise ValueError('invalid_batch')
    docs=dict(old);changed=set();observed=[]
    for event in events:
        if type(event) is not dict:raise ValueError('invalid_event')
        plain(event)
        op=event['op'];did=ident(event.get('doc_id',event.get('document',{}).get('doc_id')));changed.add(did)
        if op=='put_document':
            d=document(event['document'],p,config)
            if d.did!=did:raise ValueError('event_doc_id_mismatch')
            docs[did]=d
        elif op=='delete_document':
            if did not in docs:raise ValueError('missing_document')
            del docs[did]
        elif op=='metadata':
            d=docs[did];m=json.loads(d.metadata);m.update(event['changes']);docs[did]=Document(did,metadata(m),d.fragments)
        elif op in ('put_fragment','delete_fragment'):
            d=docs[did];fs={f.fid:f for f in d.fragments}
            if op=='put_fragment':f=fragment(event['fragment'],p,config);fs[f.fid]=f
            else:
                fid=event['fragment_id']
                if fid not in fs:raise ValueError('missing_fragment')
                del fs[fid]
            docs[did]=Document(did,d.metadata,tuple(sorted(fs.values(),key=lambda f:f.fid.encode('utf-8'))))
        else:raise ValueError('unknown_event')
        if did in docs:observed.append(docs[did])
    return docs,changed,observed

def answer(q,rows,version):return {'query_id':q.qid,'query_version':q.version,'config_version':q.config,
    'corpus_version':version,'ordered_hits':[r.hit for r in rows[:q.k]]}
def freeze(mapping):return MappingProxyType(dict(mapping))
