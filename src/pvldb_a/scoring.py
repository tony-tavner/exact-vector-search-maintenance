"""Shared blocked canonical matrix evaluator and paid optional column cache."""
from dataclasses import dataclass
import numpy as np
from .model import Row,applicable,freeze
@dataclass(frozen=True)
class CacheBlock:
    identities:tuple
    values:object
class ScoreCache:
    def __init__(self,queries,docs,previous=None):
        self.qids=tuple(queries);self.qindex={q:i for i,q in enumerate(self.qids)}
        self.blocks={d:b for d,b in (previous or {}).items() if d in docs};self.writable=set()
    def ensure(self,d):
        keys=tuple((f.fid,f.bits,f.config) for f in d.fragments);old=self.blocks.get(d.did)
        if old is not None and old.identities==keys:return old
        values=np.full((len(self.qids),len(keys)),np.nan,dtype=np.float64)
        if old is not None:
            index={k:i for i,k in enumerate(old.identities)}
            for j,k in enumerate(keys):
                if k in index:values[:,j]=old.values[:,index[k]]
        out=CacheBlock(keys,values);self.blocks[d.did]=out;self.writable.add(d.did);return out
    def writeable(self,d):
        out=self.ensure(d)
        if d.did not in self.writable:
            out=CacheBlock(out.identities,out.values.copy());self.blocks[d.did]=out;self.writable.add(d.did)
        return out
    def matrix(self,d,qids,queries,ctx,counts):
        block=self.ensure(d);rows=[self.qindex[q] for q in qids]
        if not d.fragments:return np.empty((len(rows),0))
        missing=np.isnan(block.values[rows,:]);groups={}
        for j in range(len(d.fragments)):
            indices=tuple(i for i,v in enumerate(missing[:,j]) if v)
            if indices:groups.setdefault(indices,[]).append(j)
        if groups:block=self.writeable(d)
        for ri,ci in groups.items():
            qvs=[queries[qids[i]].v for i in ri];fvs=[d.fragments[j].v for j in ci]
            values=blocked(ctx,qvs,fvs,counts)
            block.values[np.ix_([rows[i] for i in ri],ci)]=values
        counts['score_cache_hits']=counts.get('score_cache_hits',0)+int(missing.size-np.count_nonzero(missing))
        return block.values[rows,:]
    def finish(self):
        for b in self.blocks.values():b.values.flags.writeable=False
        return freeze(self.blocks)

def blocked(ctx,qs,xs,counters,query_tile=64,fragment_tile=128):
    result=np.empty((len(qs),len(xs)),dtype=np.float64)
    for i in range(0,len(qs),query_tile):
        for j in range(0,len(xs),fragment_tile):
            result[i:i+query_tile,j:j+fragment_tile]=ctx.matrix(qs[i:i+query_tile],xs[j:j+fragment_tile],counters)
    return result

def evaluate(queries,docs,ctx,counts,cache=None,only=None):
    result={qid:{} for qid in queries}
    for d in docs.values():
        qids=[qid for qid,q in queries.items() if (only is None or qid in only.get(d.did,())) and d.fragments and applicable(q,d)]
        if not qids:continue
        values=cache.matrix(d,qids,queries,ctx,counts) if cache is not None else blocked(ctx,[queries[q].v for q in qids],[f.v for f in d.fragments],counts)
        # Fragments sorted by UTF8 ID at input, so first argmax resolves exact ties.
        for i,qid in enumerate(qids):
            j=int(np.argmax(values[i]));f=d.fragments[j]
            result[qid][d.did]=Row(float(values[i,j]),d.did,f.fid,f.version)
    return result
