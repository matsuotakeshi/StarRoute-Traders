"""Offline v2 algorithm: independent industry levels, never touches a database."""
import copy
import hashlib
import uuid
from starroute.catalog import Catalog
from starroute.development import INDUSTRIES
from starroute.generation_contract import level_parameters,LEVEL_VERSION,LEVEL_RULES_VERSION
from starroute.rules import canonical_bytes
from starroute.universe import seal_manifest
from .legacy import _compile


def generate(template,parameters,levels,seed,universe_id=None):
    levels=level_parameters(copy.deepcopy(levels))
    data=_compile(template,parameters,seed,universe_id or str(uuid.uuid4()))
    # Domain-separated per-planet/per-industry draws avoid coupling the four industries.
    def draw(pid,industry,kind,bound):
        ceiling=(1<<256)-((1<<256)%bound);counter=0
        while True:
            value=int.from_bytes(hashlib.sha256(canonical_bytes([LEVEL_VERSION,seed,pid,industry,kind,counter])).digest(),'big')
            if value<ceiling:return value%bound
            counter+=1
    data['development']['mode']='linear_levels_v1'
    data.setdefault('market_events',{'mode':'disabled'})
    for planet in data['development']['planets']:
        for industry in INDUSTRIES:
            bounds=levels['maximum_ranges'][industry]
            maximum=bounds['min']+draw(planet['planet_id'],industry,'maximum',bounds['max']-bounds['min']+1)
            initial=draw(planet['planet_id'],industry,'initial',maximum+1)
            if levels['initial_policy']=='zero_v1':initial=0
            if levels['initial_policy']=='maximum_v1':initial=maximum
            planet['initial_progress'][industry]=initial
            planet['private_caps'][industry]=maximum
    data['universe'].update(format_version=2,generator_version=LEVEL_VERSION,game_rules_version=LEVEL_RULES_VERSION,industry_levels=levels)
    if 'phase3' in data:
        from starroute.rules import RULES_VERSION
        data['universe']['game_rules_version']=RULES_VERSION
    seal_manifest(data);Catalog(data)
    return data
