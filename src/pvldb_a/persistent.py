"""Immutable AVL maps for postings and version ledgers. Path copies are counted."""
from dataclasses import dataclass
@dataclass(frozen=True)
class Node:
    key: object
    value: object
    left: object=None
    right: object=None
    height: int=1

def height(n):return n.height if n else 0
def node(k,v,l=None,r=None,counter=None):
    if counter is not None:counter['avl_nodes_created']=counter.get('avl_nodes_created',0)+1
    return Node(k,v,l,r,1+max(height(l),height(r)))
def balance(k,v,l,r,c=None):
    if height(l)>height(r)+1:
        if height(l.left)<height(l.right):
            x=l.right;l=node(x.key,x.value,node(l.key,l.value,l.left,x.left,c),x.right,c)
        return node(l.key,l.value,l.left,node(k,v,l.right,r,c),c)
    if height(r)>height(l)+1:
        if height(r.right)<height(r.left):
            x=r.left;r=node(x.key,x.value,x.left,node(r.key,r.value,x.right,r.right,c),c)
        return node(r.key,r.value,node(k,v,l,r.left,c),r.right,c)
    return node(k,v,l,r,c)
def get(n,k,default=None):
    while n:
        if k==n.key:return n.value
        n=n.left if k<n.key else n.right
    return default
def put(n,k,v,c=None):
    if not n:return node(k,v,counter=c)
    if k==n.key:
        if v is n.value:return n
        return node(k,v,n.left,n.right,c)
    if k<n.key:return balance(n.key,n.value,put(n.left,k,v,c),n.right,c)
    return balance(n.key,n.value,n.left,put(n.right,k,v,c),c)
def delete(n,k,c=None):
    if not n:return None
    if k<n.key:return balance(n.key,n.value,delete(n.left,k,c),n.right,c)
    if k>n.key:return balance(n.key,n.value,n.left,delete(n.right,k,c),c)
    if not n.left:return n.right
    if not n.right:return n.left
    t=n.right
    while t.left:t=t.left
    return balance(t.key,t.value,n.left,delete(n.right,t.key,c),c)
def items(n):
    if n:
        yield from items(n.left);yield n.key,n.value;yield from items(n.right)
def posting_change(root,key,qid,add,c):
    inner=get(root,key)
    inner=put(inner,qid,True,c) if add else delete(inner,qid,c)
    return put(root,key,inner,c) if inner else delete(root,key,c)
