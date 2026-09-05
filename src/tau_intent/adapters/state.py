"""Synthetic typed-store witness. No parser, external service or benchmark."""
from __future__ import annotations
import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from urllib.parse import quote
from tau_intent.collect import collect_events
from tau_intent.neighbourhood import Graph


def _digest(present, value=None):
    data=json.dumps({'present':present,'value':value},sort_keys=True,ensure_ascii=False,
                    separators=(',',':'),allow_nan=False).encode()
    return hashlib.sha256(data).hexdigest()


def _target(namespace):
    return 'state://' + quote(namespace, safe='')


class TypedStore:
    """Closed key schema; reads and writes are snapshots, not mutable aliases."""
    def __init__(self, schema, initial=None):
        self._schema=deepcopy(schema)
        if any(not isinstance(ns,str) or not isinstance(k,str)
               for ns,keys in self._schema.items() for k in keys):
            raise TypeError('namespace and key must be strings')
        self._values={ns:{} for ns in schema}
        self.reset(initial or {})

    @property
    def schema(self):
        return deepcopy(self._schema)

    def read(self):
        return deepcopy(self._values)

    def set(self,namespace,chave,value):
        expected=self._schema[namespace][chave]
        if type(value) is not expected:
            raise TypeError(f'{namespace}/{chave}: expected {expected.__name__}')
        _digest(True,value)  # JSON value only, finite and canonically hashable
        self._values[namespace][chave]=deepcopy(value)

    def delete(self,namespace,chave):
        self._schema[namespace][chave]  # reject keys outside the closed schema
        self._values[namespace].pop(chave,None)

    def reset(self,snapshot):
        old=self._values
        self._values={ns:{} for ns in self._schema}
        try:
            for ns,values in snapshot.items():
                if ns not in self._schema:
                    raise KeyError(ns)
                for chave,value in values.items():
                    self.set(ns,chave,value)
        except Exception:
            self._values=old
            raise


@dataclass(frozen=True)
class StateAnchor:
    namespace: str
    chave: str
    value_hash: str

    def node_id(self):
        return f'{_target(self.namespace)}::{quote(self.chave,safe="")}'

    def scope_id(self):
        return _target(self.namespace)

    def overlaps(self,other):
        return isinstance(other,StateAnchor) and (self.namespace,self.chave)==(other.namespace,other.chave)


@dataclass(frozen=True)
class StateEffect:
    namespace: str
    chave: str
    before_hash: str
    value_hash: str
    resolver: str = 'typed-store-v1'
    size_unit: str = 'changed_keys'
    size: int = 1
    edited_units: int = 1

    # Compatibility properties for the existing declared-intent wire format.
    @property
    def path(self):
        return _target(self.namespace)

    @property
    def symbol(self):
        return quote(self.chave,safe='')

    def key(self):
        return (self.namespace,self.chave)

    def span(self):
        return (1,1)

    def node_id(self):
        return StateAnchor(self.namespace,self.chave,self.value_hash).node_id()


class StateAdapter:
    name='state'
    version='state-v1'
    size_unit='changed_keys'
    edge_types=('contains','depends_on')

    def __init__(self, store: TypedStore, depends_on=()):
        self.store=store
        self.before=store.read()
        self.depends_on=tuple(depends_on)
        for pair in self.depends_on:
            for ns,key in pair:
                store.schema[ns][key]

    def effects(self,workspace,supplied=None):
        if supplied is not None:
            raise ValueError('state effects must come from two independent store reads')
        after=self.store.read()
        effects=[]
        for ns,keys in sorted(self.store.schema.items()):
            for key in sorted(keys):
                a,b=self.before[ns],after[ns]
                before=_digest(key in a,a.get(key))
                current=_digest(key in b,b.get(key))
                if before != current:
                    effects.append(StateEffect(ns,key,before,current))
        return effects

    def collect(self,events,effects,workspace):
        observed={e.key() for e in effects}
        return {key:p for key,p in collect_events(events,effects).items() if key in observed}

    def identities(self,effects,workspace):
        return {StateAnchor(ns,key,'').node_id() for ns,keys in self.store.schema.items() for key in keys}

    def anchor(self,pending,workspace):
        e=pending.region
        return StateAnchor(e.namespace,e.chave,e.value_hash)

    def anchor_resolves(self,anchor):
        if not isinstance(anchor,StateAnchor):
            return False
        if anchor.chave not in self.store.schema.get(anchor.namespace,{}):
            return False
        values=self.store.read()[anchor.namespace]
        return anchor.value_hash==_digest(anchor.chave in values,values.get(anchor.chave))

    def neighbourhood(self,workspace):
        graph=Graph()
        for ns,keys in self.store.schema.items():
            graph.add_node(_target(ns),kind='namespace')
            for key in keys:
                target=StateAnchor(ns,key,'').node_id()
                graph.add_edge(_target(ns),target,'contains')
        for source,target in self.depends_on:
            graph.add_edge(StateAnchor(*source,'').node_id(),StateAnchor(*target,'').node_id(),'depends_on')
        return graph

    def oracle(self,check):
        result=check(self.store.read())
        if type(result) is not bool:
            raise TypeError('oracle must return bool')
        return result

    def classification(self,effect):
        return effect.namespace
