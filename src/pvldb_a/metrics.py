from contextlib import contextmanager
import time,resource,sys
class Metrics:
    def __init__(self):self.counts={};self.spans=[];self.stack=[]
    @contextmanager
    def span(self,name):
        event={'name':name,'start_ns':time.perf_counter_ns(),'parent':self.stack[-1] if self.stack else None}
        index=len(self.spans);self.spans.append(event);self.stack.append(index)
        try:yield
        finally:event['end_ns']=time.perf_counter_ns();self.stack.pop()
    def report(self):
        top=[s for s in self.spans if s['parent'] is None]
        return {'counts':dict(self.counts),'spans':list(self.spans),'top_level_elapsed_ns':sum(s['end_ns']-s['start_ns'] for s in top),
                'peak_self_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024),
                'timer':'perf_counter_ns','nested_spans_are_not_added_to_total':True}
