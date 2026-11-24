"""Pinned canonical scorer, guarded numerical context, exact F_OP bounds."""
from contextlib import contextmanager
from functools import lru_cache
from fractions import Fraction as F
from pathlib import Path
import ctypes,gc,hashlib,importlib.util,json,math,signal,sys,threading
import numpy as np
R=Path(__file__).resolve().parents[2]
BINDING=R/'reports/e_stages/E03/E03_2026-11-18_03/runtime_binding.json'
NATIVE=next((R/'environment/native').glob('_native*.so'))
spec=importlib.util.spec_from_file_location('pvldb_a._native',NATIVE)
native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)
U=F(1,2**53);ETA=F(1,2**1074)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
class NumericContext:
    def __init__(self,disable_box=False):
        if not native.same_fsum(math.fsum):raise RuntimeError('canonical_callable_changed')
        self.disable_box=disable_box;self.owner=None;self.active=False
        b=json.loads(BINDING.read_text())
        self.bound=False
        if sys.version==b['python'] and all(sha(x['origin'])==x['origin_sha256'] for x in b['functions'].values()):
            class ML(ctypes.Structure):
                _fields_=[('name',ctypes.c_char_p),('meth',ctypes.c_void_p),('flags',ctypes.c_int),('doc',ctypes.c_char_p)]
            class Head(ctypes.Structure):
                _fields_=[('refcnt',ctypes.c_ssize_t),('type',ctypes.c_void_p),('ml',ctypes.POINTER(ML))]
            ml=Head.from_address(id(math.fsum)).ml.contents
            x=b['functions']['fsum']
            self.bound=(ml.name==b'fsum' and hashlib.sha256(ctypes.string_at(ml.meth,x['window_bytes'])).hexdigest()==x['instruction_sha256'])
        if not native.same_fsum(math.fsum):raise RuntimeError('canonical_callable_changed')
    @contextmanager
    def region(self):
        if self.active:raise RuntimeError('nested_numeric_region')
        if not native.same_fsum(math.fsum) or native.read_fpcr()!=0:raise RuntimeError('unsupported_numeric_environment')
        if sys.gettrace() is not None or sys.getprofile() is not None:raise RuntimeError('trace_or_profile_callback')
        # Python-level arbitrary handlers can change FPCR between operations.
        safe=(signal.SIG_DFL,signal.SIG_IGN,signal.default_int_handler)
        for sig in signal.valid_signals():
            try:handler=signal.getsignal(sig)
            except (OSError,ValueError):continue
            if handler not in safe and handler is not None:raise RuntimeError('custom_signal_handler')
        enabled=gc.isenabled();gc.disable();self.owner=threading.get_ident();self.active=True
        try:
            yield self
            if native.read_fpcr()!=0 or not native.same_fsum(math.fsum):raise RuntimeError('numeric_environment_changed')
        finally:
            self.active=False;self.owner=None
            if enabled:gc.enable()
    @property
    def box_allowed(self):return self.active and self.owner==threading.get_ident() and self.bound and not self.disable_box and native.read_fpcr()==0
    def matrix(self,qs,xs,counters):
        if not self.active or self.owner!=threading.get_ident():raise RuntimeError('outside_numeric_region')
        if not qs or not xs:return np.empty((len(qs),len(xs)),dtype=np.float64)
        q=np.ascontiguousarray(qs,dtype=np.float64);x=np.ascontiguousarray(xs,dtype=np.float64)
        q.flags.writeable=False;x.flags.writeable=False
        data=native.matrix(q,x)
        counters['score_pairs']=counters.get('score_pairs',0)+len(qs)*len(xs)
        counters['matrix_calls']=counters.get('matrix_calls',0)+1
        counters['score_coordinates']=counters.get('score_coordinates',0)+len(qs)*len(xs)*q.shape[1]
        return np.frombuffer(data,dtype=np.float64).reshape(len(qs),len(xs))

def error_fsum(p,A):
    L=p*(p-1)//2;H=(A+3*L*ETA)/(1-4*L*U);G=(H+p*ETA/2)/(1-p*U)
    return L*(2*U*H+2*ETA)+(p+8)*U*G+3*p*U*H+(4*p+8)*ETA
@lru_cache(maxsize=128)
def coefficients(p):
    def e(a):return U*a+p*ETA/2+error_fsum(p,(1+U)*a+p*ETA/2)
    beta=e(F(0));return e(F(1))-beta,beta

def bounds(box,z,w=None,context=None,counters=None,separate=False):
    p=len(box)
    if context is None or not context.box_allowed or not 1<=p<=2**20 or len(z)!=p or (w is not None and len(w)!=p):return None
    S=F(0);Az=F(0);Aw=F(0)
    for i,((lo,hi),a) in enumerate(zip(box,z)):
        b=0. if w is None else w[i]
        if any(not math.isfinite(v) or abs(v)>2 for v in (lo,hi,a,b)) or lo>hi:return None
        lo,hi,a,b=map(F,(lo,hi,a,b));v=max(abs(lo),abs(hi))
        S+=(max(lo*a,hi*a)-min(lo*b,hi*b)) if separate else max(lo*(a-b),hi*(a-b))
        Az+=v*abs(a);Aw+=v*abs(b)
    alpha,beta=coefficients(p)
    if counters is not None:
        counters['bound_pairs']=counters.get('bound_pairs',0)+1
        counters['bound_coordinates']=counters.get('bound_coordinates',0)+p
    return S+alpha*Az+beta if w is None else S+alpha*(Az+Aw)+2*beta

def norm2(v):return sum((F(x)*F(x) for x in v),F(0))
def sqrt_upper(x):
    # Exact integer construction of an outward square-root at fixed absolute grid.
    scale=2**53;n=x.numerator*scale*scale;d=x.denominator;r=math.isqrt(n//d)
    if r*r*d<n:r+=1
    return F(r,scale)
def norm_upper(qnorm2,x,context):
    p=len(x)
    if not context.box_allowed or not 1<=p<=2**20 or any(not math.isfinite(v) or abs(v)>2 for v in x):return None
    a=sqrt_upper(qnorm2*norm2(x));alpha,beta=coefficients(p)
    return a+alpha*a+beta
