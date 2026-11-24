"""Pinned local cold preparation. Sequential subprocesses, no network or model download."""
from pathlib import Path
import copy,hashlib,json,math,os,signal,struct,subprocess,time
R=Path(__file__).resolve().parents[2]
CONFIG=json.loads((R/'data/processed/onet29_3_v1/embedding_config.json').read_text())
INVOCATION=json.loads((R/'data/processed/onet29_3_v1/embeddings_development/invocation.json').read_text())
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()
class LocalEmbeddings:
    def __init__(self,out,timeout=120):
        self.out=Path(out);self.out.mkdir(parents=True,exist_ok=False);self.timeout=timeout;self.calls=[];self.cache={}
        self.binary=Path(INVOCATION['binary_resolved']);self.model=R/CONFIG['weights_local_path']
        if sha(self.binary)!=INVOCATION['binary_sha256'] or sha(self.model)!=CONFIG['weights_sha256']:raise ValueError('embedding_assets_changed')
    def vector_digest(self):
        h=hashlib.sha256()
        for key in sorted(self.cache):
            h.update(json.dumps(key,ensure_ascii=False).encode('utf8'));v=self.cache[key]
            h.update(struct.pack('='+str(len(v))+'d',*v))
        return h.hexdigest()
    def embed(self,items):
        # Same within-run text cache is available to every method; no cross-run reuse in cold mode.
        missing=list(dict.fromkeys(items))
        missing=[x for x in missing if x not in self.cache]
        if missing:
            d=self.out/f'call_{len(self.calls)+1:03d}';d.mkdir()
            texts=[('search_query: ' if kind=='query' else 'search_document: ')+text for kind,text in missing]
            if any('\n' in text or '\r' in text for text in texts):raise ValueError('embedding_input_must_be_single_line')
            inp=d/'input.txt';inp.write_text('\n'.join(texts)+'\n')
            command=[str(self.binary),'--offline','-m',str(self.model),'-ngl','0','-t','4','-c','2048','-b','2048','-ub','2048',
                '--pooling','mean','--embd-normalize','2','--embd-output-format','json','-f',str(inp)]
            env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OLLAMA_NO_CLOUD='1')
            started=time.perf_counter_ns();timeout=False
            with (d/'raw.json').open('w') as out,(d/'stderr.txt').open('w') as err:
                child=subprocess.Popen(command,stdout=out,stderr=err,env=env)
                while True:
                    pid,status,usage=os.wait4(child.pid,os.WNOHANG)
                    if pid:break
                    if (time.perf_counter_ns()-started)/1e9>self.timeout:
                        child.kill();pid,status,usage=os.wait4(child.pid,0);timeout=True;break
                    time.sleep(.005)
                child.returncode=os.waitstatus_to_exitcode(status)
            record={'command':command,'pid':child.pid,'exit_code':child.returncode,'timeout':timeout,'wall_ns':time.perf_counter_ns()-started,
                    'peak_child_rss_bytes':usage.ru_maxrss,'input_sha256':sha(inp),'texts':len(missing),'network_used':False}
            self.calls.append(record);(d/'invocation.json').write_text(json.dumps(record,indent=2)+'\n')
            if child.returncode or timeout:raise RuntimeError('local_embedding_failed')
            values=json.loads((d/'raw.json').read_text())['data']
            if len(values)!=len(missing):raise ValueError('embedding_count_mismatch')
            for i,(item,entry) in enumerate(zip(missing,values)):
                if entry['index']!=i:raise ValueError('embedding_index_mismatch')
                v=[float(x) for x in entry['embedding']]
                if len(v)!=768 or not all(math.isfinite(x) for x in v):raise ValueError('invalid_embedding')
                norm=math.sqrt(math.fsum(x*x for x in v))
                if norm<=0:raise ValueError('zero_embedding')
                v=[x/norm for x in v]
                if abs(math.fsum(x*x for x in v)-1)>1e-12:raise ValueError('unnormalized_embedding')
                self.cache[item]=tuple(v)
        return [list(self.cache[x]) for x in items]
    def prepare(self,docs=None,queries=None,events=None):
        docs=copy.deepcopy(docs);queries=copy.deepcopy(queries);events=copy.deepcopy(events)
        targets=[]
        for d in docs or []:
            for f in d['fragments']:targets.append(('document',f['text'],f))
        for q in queries or []:
            if q['config_version']!=CONFIG['config_version']:raise ValueError('embedding_config_mismatch')
            targets.append(('query',q['query_text'],q))
        for event in events or []:
            if event['op']=='put_document':
                for f in event['document']['fragments']:targets.append(('document',f['text'],f))
            elif event['op']=='put_fragment':f=event['fragment'];targets.append(('document',f['text'],f))
        values=self.embed([(kind,text) for kind,text,target in targets])
        for (_,_,target),v in zip(targets,values):target['vector']=v
        return docs,queries,events
