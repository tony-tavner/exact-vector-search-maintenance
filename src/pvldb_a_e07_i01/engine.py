"""Atomic exact implementations and explicit author reimplementations of B0--B6."""
from contextlib import contextmanager
from dataclasses import dataclass
from fractions import Fraction as F
import heapq,json,math,threading,time
from .model import *
from .numeric import NumericContext,bounds,norm_upper,norm2,sqrt_upper,coefficients
from .blocks import build_blocks,Block
from .scoring import evaluate,ScoreCache
from .metrics import Metrics
from .reserve import Adaptive
from . import persistent as avl
METHODS=('C1','B0_FULL_EXACT','B1_DELTA_MATRIX','B2_RESERVE_EXACT','B2_ADAPTIVE','B3_ALL_SCORES',
         'B4_SIMPFER_EXACT','B5_SIMPFERPP_EXACT','B6_HYBRID_EXACT','C1_FLAT','C1_SEPARATE','C1_MARGIN','C1_NO_CERT')
@dataclass(frozen=True)
class Root:
    version:str;config:str;dimension:int;docs:object;queries:object;reserves:object;caps:object
    blocks:tuple;membership:object;rev:object;small:frozenset;ledger:object;cache:object;adaptive:object;epoch:int
    all_rows:object=None
    sample:frozenset=frozenset()
    norm_cache:object=None
class Reader:
    def __init__(self,root):self._root=root;self._open=True
    def answers(self):
        if not self._open:raise RuntimeError('reader_released')
        return {qid:answer(q,self._root.reserves[qid],self._root.version) for qid,q in self._root.queries.items()}
class Engine:
    def __init__(self,method='C1',cap=None,leaf_limit=64,certificate_budget=2**20,hybrid_fraction=.3,disable_box=False):
        start=time.perf_counter_ns()
        if method not in METHODS:raise ValueError('unknown_method')
        if cap is not None and (type(cap) is not int or cap<1):raise ValueError('invalid_cap')
        if type(certificate_budget) is not int or certificate_budget<0:raise ValueError('invalid_certificate_budget')
        if type(leaf_limit) is not int or leaf_limit<1:raise ValueError('invalid_leaf_limit')
        if not 0<=hybrid_fraction<=1:raise ValueError('invalid_hybrid_fraction')
        self.method=method;self.cap=cap;self.leaf_limit=leaf_limit;self.budget=certificate_budget;self.hybrid_fraction=hybrid_fraction
        self.ctx=NumericContext(disable_box);self._root=None;self._lock=threading.RLock();self._pins={};self.last_metrics={}
        self.setup_ns=time.perf_counter_ns()-start
    def _cache(self,qs,docs,prior=None):
        return ScoreCache(qs,docs,prior) if self.method in ('B3_ALL_SCORES','B4_SIMPFER_EXACT','B5_SIMPFERPP_EXACT','C1_MARGIN') else None
    def _revkey(self,did,qid,membership):return (did.encode('utf8'),) if self.method=='C1_FLAT' else (did.encode('utf8'),membership[qid])
    def _initial(self,docs,qs,version,config,p,ledger,m,epoch,cap_override=None):
        with m.span('partition_build'):
            if self.method.startswith('C1') or self.method in ('B4_SIMPFER_EXACT','B5_SIMPFERPP_EXACT'):
                policy='norm' if self.method in ('B4_SIMPFER_EXACT','B5_SIMPFERPP_EXACT') else 'kd'
                blocks,membership=build_blocks(qs,self.leaf_limit,policy,need_norm=self.method in ('B4_SIMPFER_EXACT','B5_SIMPFERPP_EXACT'))
            else:
                blocks=(Block(0,tuple(qs),(),F(0)),) if qs else ()
                membership={i:0 for i in qs}
        caps={qid:(cap_override if cap_override is not None else self.cap or max(q.k,2*q.k)) for qid,q in qs.items()}
        if self.method in ('B0_FULL_EXACT','B1_DELTA_MATRIX','B3_ALL_SCORES'):caps={i:q.k for i,q in qs.items()}
        if any(type(caps[i]) is not int or caps[i]<q.k for i,q in qs.items()):raise ValueError('invalid_cap')
        if self.method=='B2_ADAPTIVE':caps={i:max(q.k,math.ceil(len(docs)**.6)) for i,q in qs.items()}
        cache=self._cache(qs,docs)
        start=time.perf_counter_ns()
        with m.span('full_search'):
            rows=evaluate(qs,docs,self.ctx,m.counts,cache)
            reserves={i:tuple(sorted(rows[i].values(),key=lambda r:r.key)[:caps[i]]) for i in qs}
        elapsed=time.perf_counter_ns()-start
        if self.method in ('B3_ALL_SCORES','C1_MARGIN'):
            with m.span('all_score_cache_fill'):
                for d in docs.values():cache.matrix(d,list(qs),qs,self.ctx,m.counts)
        sample=frozenset();norm_cache={}
        if self.method=='B4_SIMPFER_EXACT':
            # Retain a norm-ordered sample only; initial full response is already paid.
            sample,norm_cache=self._sample(docs,caps);cache.blocks={d:b for d,b in cache.blocks.items() if d in sample}
        rev=None
        with m.span('postings_build'):
            for qid,rs in reserves.items():
                if self.method in ('B0_FULL_EXACT','B3_ALL_SCORES'):continue
                for r in rs:rev=avl.posting_change(rev,self._revkey(r.did,qid,membership),qid,True,m.counts)
        adaptive={i:Adaptive(caps[i],caps[i],refill_ns=elapsed/max(1,len(qs))) for i in qs} if self.method=='B2_ADAPTIVE' else {}
        return Root(version,config,p,freeze(docs),freeze(qs),freeze(reserves),freeze(caps),blocks,freeze(membership),rev,
                    frozenset(i for i,q in qs.items() if len(reserves[i])<q.k),ledger,cache.finish() if cache else freeze({}),freeze(adaptive),epoch,
                    freeze({i:freeze(rows[i]) for i in qs}) if self.method=='B3_ALL_SCORES' else None,sample,freeze(norm_cache))
    def build(self,documents,queries,corpus_version,config=None,dimension=None):
        m=Metrics()
        with self._lock:
            if self._root is not None:raise RuntimeError('already_initialized')
            with m.span('build_total'):
                with self.ctx.region():
                    with m.span('validation'):
                        qs=parse_queries(queries)
                        if qs:q=next(iter(qs.values()));p=len(q.v);config=q.config
                        else:p=dimension
                        if not config or type(p) is not int or p<1:raise ValueError('empty_registry_needs_config_dimension')
                        docs=parse_documents(documents,p,config);version=ident(corpus_version)
                        ledger=register(None,docs.values(),qs.values(),m.counts)
                        ledger=avl.put(ledger,('c',version),True,m.counts)
                    new=self._initial(docs,qs,version,config,p,ledger,m,0)
                # Environment checked on region exit, before the single publication.
                self._root=new
            self.last_metrics=m.report();return self.answers()
    @contextmanager
    def pin(self):
        with self._lock:
            root=self._root
            if root is None:raise RuntimeError('not_initialized')
            key=id(root);self._pins[key]=self._pins.get(key,0)+1;reader=Reader(root)
        try:yield reader
        finally:
            with self._lock:
                reader._open=False;self._pins[key]-=1
                if not self._pins[key]:del self._pins[key]
    def answers(self):
        with self.pin() as reader:return reader.answers()
    def _sample(self,docs,caps,prior=None):
        count=2*max(caps.values(),default=1)
        norms={};prior=prior or {}
        for d in docs.values():
            keys=tuple(f.bits for f in d.fragments);old=prior.get(d.did)
            norms[d.did]=old if old is not None and old[0]==keys else (keys,max((norm2(f.v) for f in d.fragments),default=F(0)))
        chosen=heapq.nsmallest(count,docs,key=lambda did:(-norms[did][1],did.encode('utf8')))
        return frozenset(chosen),norms
    def _cover(self,old,new,block,m,cache=None,oldroot=None):
        if old is None or new is None or old.metadata!=new.metadata:return False
        oldf={f.fid:f for f in old.fragments};newf={f.fid:f for f in new.fragments}
        # Absent source bytes are not evidence of unchanged content. Legacy toy
        # fixtures without text use exact fallback, not a fabricated identity.
        common={k for k in oldf if k in newf and oldf[k].text is not None and oldf[k].identity==newf[k].identity}
        if not common:return False
        delta=[f for f in old.fragments if f.fid not in common]+[f for f in new.fragments if f.fid not in common]
        if not delta:return True
        w=oldf[min(common,key=lambda x:x.encode('utf8'))]
        if self.method=='C1_MARGIN':
            # Per-query cache control. Norm-delta/gap attempt, then exact paid cache fallback.
            for qid in block.members:
                q=oldroot.queries[qid]
                oldmatrix=oldroot.cache[old.did].values;qi=list(oldroot.queries).index(qid)
                oldindex={f.fid:j for j,f in enumerate(old.fragments)}
                sw=float(oldmatrix[qi,oldindex[w.fid]])
                for f in delta:
                    is_old=any(f is t for t in old.fragments)
                    if not is_old and f.fid in oldindex and self.ctx.box_allowed and 1<=len(q.v)<=2**20:
                        previous=oldf[f.fid];gap=F(sw)-F(float(oldmatrix[qi,oldindex[f.fid]]))
                        diff=tuple(F(a)-F(b) for a,b in zip(f.v,previous.v))
                        norm=sqrt_upper(norm2(q.v)*sum((x*x for x in diff),F(0)))
                        alpha,beta=coefficients(len(q.v))
                        err=alpha*(sum(abs(F(a)*F(b)) for a,b in zip(q.v,f.v))+sum(abs(F(a)*F(b)) for a,b in zip(q.v,previous.v)))+2*beta
                        m.counts['margin_attempts']=m.counts.get('margin_attempts',0)+1
                        if norm+err<gap:continue
                    if is_old:sz=float(oldmatrix[qi,oldindex[f.fid]])
                    else:
                        mat=cache.matrix(new,[qid],oldroot.queries,self.ctx,m.counts);sz=float(mat[0,next(j for j,t in enumerate(new.fragments) if t.fid==f.fid)])
                    if not sz<sw:return False
            return True
        for z in delta:
            value=bounds(block.box,z.v,w.v,self.ctx,m.counts,separate=self.method=='C1_SEPARATE')
            if value is None or value>=0:return False
        return True
    def _threshold_survivors(self,old,docs,D,m,cache):
        """Reverse-query filtering against the frozen reserve admission frontier.
        B4 sample lower bound <= that frontier; B5 uses its exact value. A short
        candidate prefix invokes full refill, so old witnesses need not remain live.
        """
        qs=old.queries;thresholds={}
        if self.method=='B4_SIMPFER_EXACT':
            sample=old.sample
            # Current-old sample values maintained lazily; affected/new sample work is paid.
            sc=ScoreCache(qs,old.docs,old.cache)
            sr=evaluate(qs,{d:old.docs[d] for d in sample},self.ctx,m.counts,sc)
            for i,q in qs.items():
                ell=len(old.reserves[i]);values=sorted((r.score for r in sr[i].values()),reverse=True)
                thresholds[i]=values[ell-1] if ell>=q.k and len(values)>=ell else -math.inf
        else:
            thresholds={i:old.reserves[i][-1].score if len(old.reserves[i])>=q.k else -math.inf for i,q in qs.items()}
        only={d:set() for d in D if d in docs}
        for did in only:
            d=docs[did]
            if not d.fragments:continue
            for b in old.blocks:
                eligible=[i for i in b.members if applicable(qs[i],d)]
                if not eligible:continue
                m.counts['reverse_blocks_visited']=m.counts.get('reverse_blocks_visited',0)+1
                lows=[thresholds[i] for i in eligible]
                ub=None
                if self.ctx.box_allowed:
                    fs=[]
                    for f in d.fragments:
                        nu=norm_upper(b.max_norm2,f.v,self.ctx);bu=bounds(b.box,f.v,context=self.ctx,counters=m.counts)
                        if nu is None or bu is None:fs=[];break
                        fs.append(min(nu,bu))
                    if fs:ub=max(fs)
                # Strict rejection preserves ID ties. Incomplete sample => -inf.
                if ub is not None and all(t!=-math.inf and ub<F(t) for t in lows):
                    m.counts['reverse_blocks_pruned']=m.counts.get('reverse_blocks_pruned',0)+1;continue
                for i in eligible:
                    if self.method=='B4_SIMPFER_EXACT' and thresholds[i]!=-math.inf:
                        vals=[bounds(tuple(zip(qs[i].v,qs[i].v)),f.v,context=self.ctx,counters=m.counts) for f in d.fragments]
                        if all(v is not None for v in vals) and max(vals)<F(thresholds[i]):continue
                    only[did].add(i)
        return only
    def _incremental(self,old,docs,D,version,ledger,m,fault_at):
        qs=old.queries;cache=self._cache(qs,docs,old.cache);cert=set();caps=dict(old.caps);adaptive=dict(old.adaptive)
        if self.method in ('B3_ALL_SCORES','C1_MARGIN'):
            with m.span('changed_score_columns'):
                for did in D:
                    if did in docs:cache.matrix(docs[did],list(qs),qs,self.ctx,m.counts)
        if self.method=='B3_ALL_SCORES':
            with m.span('all_score_aggregation'):
                changed=evaluate(qs,{d:docs[d] for d in D if d in docs},self.ctx,m.counts,cache)
                rows={i:dict(old.all_rows[i]) for i in qs}
                for i in qs:
                    for d in D:rows[i].pop(d,None)
                    rows[i].update(changed[i])
                reserves={i:tuple(sorted(rows[i].values(),key=lambda r:r.key)[:caps[i]]) for i in qs}
        else:
            if self.method in ('C1','C1_FLAT','C1_SEPARATE','C1_MARGIN'):
                with m.span('certificates'):
                    for did in sorted(D,key=lambda x:x.encode('utf8')):
                        for b in old.blocks:
                            m.counts['cells_visited']=m.counts.get('cells_visited',0)+1
                            if len(cert)>=self.budget:continue
                            if self._cover(old.docs.get(did),docs.get(did),b,m,cache,old):cert.add((did,b.bid))
                    m.counts['certified_cells']=len(cert)
            affected=lambda i,d:d in D and (d,old.membership[i]) not in cert
            touched=set(old.small)
            if self.method=='B2_ADAPTIVE':touched.update(qs)
            with m.span('postings_lookup'):
                if self.method=='C1_FLAT':
                    for did in D:
                        for i,_ in avl.items(avl.get(old.rev,(did.encode('utf8'),))):
                            m.counts['postings_visited']=m.counts.get('postings_visited',0)+1
                            if affected(i,did):touched.add(i)
                else:
                    for did in D:
                        for b in old.blocks:
                            if (did,b.bid) in cert:continue
                            for i,_ in avl.items(avl.get(old.rev,(did.encode('utf8'),b.bid))):
                                m.counts['postings_visited']=m.counts.get('postings_visited',0)+1;touched.add(i)
            only={did:{i for i in qs if affected(i,did)} for did in D if did in docs}
            with m.span('reverse_filter'):
                if self.method in ('B4_SIMPFER_EXACT','B5_SIMPFERPP_EXACT'):only=self._threshold_survivors(old,docs,D,m,cache)
            delta_started=time.perf_counter_ns()
            with m.span('delta_scoring'):
                scored=evaluate(qs,{d:docs[d] for d in D if d in docs},self.ctx,m.counts,cache,only)
                admitted={i:{} for i in qs}
                for i,rows in scored.items():
                    boundary=old.reserves[i][-1].key if old.reserves[i] else None
                    for did,row in rows.items():
                        if boundary is None or row.key<=boundary:admitted[i][did]=row;touched.add(i)
            shared_update_ns=(time.perf_counter_ns()-delta_started)/max(1,len(qs))
            reserves=dict(old.reserves)
            with m.span('reserve_maintenance'):
                for i in sorted(touched):
                    start=time.perf_counter_ns();q=qs[i]
                    candidates={r.did:r for r in old.reserves[i] if not affected(i,r.did)};candidates.update(admitted[i])
                    rows=sorted(candidates.values(),key=lambda r:r.key)
                    if self.method=='B2_ADAPTIVE':
                        adaptive[i]=adaptive[i].observe(q.k,len(rows),max(1,len(D)),shared_update_ns+time.perf_counter_ns()-start)
                    if len(rows)<q.k:
                        if self.method=='B2_ADAPTIVE':adaptive[i]=adaptive[i].before_refill(q.k,len(docs));caps[i]=adaptive[i].cap
                        with m.span('full_refill'):
                            start=time.perf_counter_ns();full=evaluate({i:q},docs,self.ctx,m.counts,cache)
                            rows=sorted(full[i].values(),key=lambda r:r.key)
                            elapsed=time.perf_counter_ns()-start
                        m.counts['full_refills']=m.counts.get('full_refills',0)+1
                        if self.method=='B2_ADAPTIVE':adaptive[i]=adaptive[i].after_refill(elapsed)
                    elif self.method=='B2_ADAPTIVE':adaptive[i]=adaptive[i].shrink(q.k);caps[i]=adaptive[i].cap
                    reserves[i]=tuple(rows[:caps[i]])
        if fault_at=='after_scoring':raise RuntimeError('injected_after_scoring')
        with m.span('postings_update'):
            rev=old.rev
            for i,rs in reserves.items():
                if self.method=='B3_ALL_SCORES':continue
                if rs==old.reserves[i]:continue
                before={r.did for r in old.reserves[i]};after={r.did for r in rs}
                for did in before-after:rev=avl.posting_change(rev,self._revkey(did,i,old.membership),i,False,m.counts)
                for did in after-before:rev=avl.posting_change(rev,self._revkey(did,i,old.membership),i,True,m.counts)
        sample=old.sample;norm_cache=old.norm_cache
        if self.method=='B4_SIMPFER_EXACT':
            # Populate/refresh only the selected sample for the newly committed snapshot.
            sample,norm_cache=self._sample(docs,caps,old.norm_cache)
            with m.span('sample_threshold_maintenance'):
                evaluate(qs,{d:docs[d] for d in sample},self.ctx,m.counts,cache)
                cache.blocks={d:b for d,b in cache.blocks.items() if d in sample}
        return Root(version,old.config,old.dimension,freeze(docs),qs,freeze(reserves),freeze(caps),old.blocks,old.membership,rev,
            frozenset(i for i,q in qs.items() if len(reserves[i])<q.k),ledger,cache.finish() if cache else freeze({}),freeze(adaptive),old.epoch,
            freeze({i:freeze(rows[i]) for i in qs}) if self.method=='B3_ALL_SCORES' else None,sample,freeze(norm_cache))
    def apply(self,events,corpus_version,expected_corpus_version,queries=None,documents=None,cap=None,fault_at=None):
        m=Metrics()
        with self._lock:
            old=self._root
            if old is None:raise RuntimeError('not_initialized')
            if any(key!=id(old) for key in self._pins):raise RuntimeError('reader_backpressure')
            if expected_corpus_version!=old.version:raise ValueError('stale_corpus_version')
            try:
                with m.span('update_total'):
                    with self.ctx.region():
                        with m.span('validation'):
                            version=ident(corpus_version)
                            if avl.get(old.ledger,('c',version)) is not None:raise ValueError('corpus_version_reuse')
                            qs=parse_queries(queries) if queries is not None else old.queries
                            if cap is not None and (type(cap) is not int or cap<max((q.k for q in qs.values()),default=1)):raise ValueError('invalid_cap')
                            q=next(iter(qs.values()),None);config=q.config if q else old.config;p=len(q.v) if q else old.dimension
                            changed_config=config!=old.config or p!=old.dimension
                            if changed_config and documents is None:raise ValueError('config_rebuild_requires_all_documents')
                            if documents is not None:
                                if events:raise ValueError('full_snapshot_and_events_conflict')
                                docs=parse_documents(documents,p,config);D=set(old.docs)|set(docs);observed=list(docs.values())
                            else:docs,D,observed=events_to_documents(old.docs,events,p,config)
                            ledger=register(old.ledger,observed,qs.values() if queries is not None else (),m.counts)
                            ledger=avl.put(ledger,('c',version),True,m.counts)
                            rebuild=queries is not None or changed_config or cap is not None
                        if fault_at=='after_validation':raise RuntimeError('injected_after_validation')
                        full=self.method=='B0_FULL_EXACT' or (self.method=='B6_HYBRID_EXACT' and len(D)/max(1,len(old.docs))>=self.hybrid_fraction)
                        if rebuild or full:
                            m.counts['full_rebuilds']=1
                            new=self._initial(docs,qs,version,config,p,ledger,m,old.epoch+1,cap_override=cap)
                        else:new=self._incremental(old,docs,D,version,ledger,m,fault_at)
                        with m.span('answer_materialization'):
                            outputs={i:answer(q,new.reserves[i],version) for i,q in qs.items()}
                        if fault_at=='before_publish':raise RuntimeError('injected_before_publish')
                    with m.span('publication'):
                        self._root=new
                        if cap is not None:self.cap=cap
                self.last_metrics=m.report();return outputs
            except BaseException:
                self.last_metrics=dict(m.report(),failed=True);raise
    def check_invariants(self):
        """Expensive external diagnostic, not called by update or included as free work."""
        with self._lock:
            root=self._root;expected={}
            for i,rs in root.reserves.items():
                assert list(rs)==sorted(rs,key=lambda r:r.key)
                assert len({r.did for r in rs})==len(rs)
                assert len(rs)<=root.caps[i]
                if self.method not in ('B0_FULL_EXACT','B3_ALL_SCORES'):
                    for r in rs:expected.setdefault(self._revkey(r.did,i,root.membership),set()).add(i)
            actual={k:{i for i,_ in avl.items(v)} for k,v in avl.items(root.rev)}
            assert expected==actual
            assert root.small==frozenset(i for i,q in root.queries.items() if len(root.reserves[i])<q.k)
            for b in root.blocks:
                for i in b.members:assert all(lo<=x<=hi for (lo,hi),x in zip(b.box,root.queries[i].v))
            return True
