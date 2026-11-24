"""Yi-style cap adaptation; fixed reserve is the default exact variant."""
from dataclasses import dataclass,replace
import math
@dataclass(frozen=True)
class Adaptive:
    cap:int;kmin:int;T:float=0.;refill_ns:float=0.;update_ns:float=0.;updates:int=0
    def observe(self,k,remaining,base_updates,elapsed_ns):
        count=self.updates+base_updates
        mean=(self.update_ns*self.updates+elapsed_ns)/count if count else 0.
        return replace(self,T=self.T+base_updates,kmin=min(self.kmin,remaining),update_ns=mean,updates=count)
    def before_refill(self,k,N):
        cap=self.cap
        if self.update_ns>0 and self.T>0:
            Z=self.refill_ns/self.update_ns
            if self.T<Z/2:cap=math.ceil(min((Z/(2*self.T))*cap,1.5*cap))
        cap=max(k,min(max(N,k),cap))
        return replace(self,cap=cap)
    def after_refill(self,elapsed_ns):return replace(self,T=0.,kmin=self.cap,refill_ns=float(elapsed_ns))
    def shrink(self,k):
        if self.update_ns<=0:return self
        Z=self.refill_ns/self.update_ns
        if self.T>2*Z:
            cap=max(k,math.ceil(self.cap-.5*(self.kmin-k)))
            return replace(self,cap=cap,kmin=math.ceil(self.kmin-.5*(self.kmin-k)),T=Z)
        return self
