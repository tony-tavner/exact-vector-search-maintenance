from dataclasses import dataclass
from fractions import Fraction as F
from .numeric import norm2
@dataclass(frozen=True)
class Block:
    bid:int;members:tuple;box:tuple;max_norm2:object

def build_blocks(queries,limit=64,policy='kd',need_norm=True):
    if type(limit) is not int or limit<1:raise ValueError('invalid_leaf_limit')
    if not queries:return (),{}
    leaves=[];p=len(next(iter(queries.values())).v)
    def split(ids):
        if len(ids)<=limit:leaves.append(ids);return
        widths=[max(F(queries[i].v[j]) for i in ids)-min(F(queries[i].v[j]) for i in ids) for j in range(p)]
        j=max(range(p),key=lambda j:(widths[j],-j));order=sorted(ids,key=lambda i:(queries[i].v[j],i.encode('utf8')))
        mid=len(order)//2;split(order[:mid]);split(order[mid:])
    ids=sorted(queries,key=lambda x:x.encode('utf8'))
    norms={i:norm2(queries[i].v) for i in ids} if need_norm or policy=='norm' else {}
    if policy=='norm':
        ids.sort(key=lambda x:(-norms[x],x.encode('utf8')))
        leaves=[ids[i:i+limit] for i in range(0,len(ids),limit)]
    else:split(ids)
    blocks=[];membership={}
    for bid,ids in enumerate(leaves):
        box=tuple((min(queries[i].v[j] for i in ids),max(queries[i].v[j] for i in ids)) for j in range(p))
        blocks.append(Block(bid,tuple(ids),box,max(norms[i] for i in ids) if need_norm else None))
        membership.update({i:bid for i in ids})
    return tuple(blocks),membership
