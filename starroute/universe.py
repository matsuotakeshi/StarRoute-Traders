"""Runtime validation of frozen definitions. No generator execution on load.

Private definitions stay on the master; BBS views use MasterService.
"""
import copy
import hashlib
import json
import uuid
from pathlib import Path
from .model import GameError, integer

VERSION = 'srt-universe-trial-v1'
GENERATION_RULES_VERSION = 'phase3-universe-1'


def normal_planets():
    rows=json.loads((Path(__file__).parent/'data/normal-planets.json').read_text(encoding='utf-8'))['planets']
    if [r['id'] for r in rows]!=[f'{n:03}' for n in range(1,49)]:raise ValueError('normal planets')
    return rows


def _definition(data):
    """Immutable initial universe, without display names, identity, or mutable DB state."""
    result=copy.deepcopy({k:v for k,v in data.items() if k!='universe'})
    for group in ('planets','goods','ships'):
        for row in result[group]:row.pop('name',None)
    if 'private_world' in data['universe']:result['private_world']=copy.deepcopy(data['universe']['private_world'])
    result['coordinates']=copy.deepcopy(data['universe']['coordinates'])
    from .rules import canonical_bytes
    def normalized(value):
        if isinstance(value,dict):return {k:normalized(v) for k,v in value.items()}
        if isinstance(value,list):return sorted((normalized(v) for v in value),key=canonical_bytes)
        return value
    return normalized(result)


def _hash(data):
    from .rules import canonical_bytes
    return hashlib.sha256(canonical_bytes(_definition(data))).hexdigest()


def manifest_hash(raw):
    from .rules import canonical_bytes
    def norm(v):
        if isinstance(v,dict):return {k:norm(x) for k,x in v.items()}
        if isinstance(v,list):return sorted((norm(x) for x in v),key=canonical_bytes)
        return v
    return hashlib.sha256(canonical_bytes(norm({k:v for k,v in raw.items() if k!='manifest_hash'}))).hexdigest()


def seal_manifest(data):
    data['universe']['definition_hash']=_hash(data)
    data['universe']['manifest_hash']=manifest_hash(data['universe'])


def validate(catalog):
    """Structural/rule validation and corruption detection, NOT authentication."""
    raw=catalog.data.get('universe')
    if raw is None:return
    from .generation_contract import parameters,_template,level_parameters,LEVEL_VERSION,LEVEL_RULES_VERSION,CONNECTED_VERSION,CONNECTED_RULES_VERSION
    from .catalog import identifier
    from .rules import canonical_bytes
    required={'format_version','generator_version','game_rules_version','universe_id','seed','parameters','template','coordinates','definition_hash'}
    if not isinstance(raw,dict) or set(raw)-required-{'manifest_hash','industry_levels','private_world'} or required-set(raw):raise ValueError('universe fields')
    connected=raw['generator_version']==CONNECTED_VERSION
    modern=raw['generator_version'] in (LEVEL_VERSION,CONNECTED_VERSION)
    if type(raw['format_version']) is not int or raw['format_version']!=(3 if connected else 2 if modern else 1):raise ValueError('universe format')
    from .rules import RULES_VERSION
    expected_rules=CONNECTED_RULES_VERSION if connected else RULES_VERSION if modern and 'phase3' in catalog.data else LEVEL_RULES_VERSION if modern else GENERATION_RULES_VERSION
    if raw['generator_version'] not in (VERSION,LEVEL_VERSION,CONNECTED_VERSION) or raw['game_rules_version']!=expected_rules:raise ValueError('universe version')
    if not isinstance(raw['universe_id'],str) or str(uuid.UUID(raw['universe_id']))!=raw['universe_id']:raise ValueError('universe id')
    identifier(raw['seed']);params=parameters(raw['parameters']);source=_template(raw['template'])
    if connected!=(params['mode']=='grid_mst_connected_v2'):raise ValueError('generator policy version')
    if connected:
        if catalog.market_buyback is None:raise ValueError('missing buyback policy')
        from .hidden_world import validate_hidden
        validate_hidden(catalog)
    elif 'private_world' in raw:raise ValueError('unexpected private world')
    if catalog.phase3!=source.phase3:raise ValueError('phase3 rule mismatch')
    if catalog.exploration!=source.exploration:raise ValueError('exploration rule mismatch')
    if catalog.market_buyback!=source.market_buyback:raise ValueError('buyback rule mismatch')
    if catalog.phase3 is not None and (params['width'],params['height'])!=(240,120):raise ValueError('phase3 chart dimensions')
    if modern:level_parameters(raw['industry_levels'])
    elif 'industry_levels' in raw:raise ValueError('unexpected level policy')
    if modern and 'manifest_hash' not in raw:raise ValueError('missing manifest checksum')
    if 'manifest_hash' in raw and raw['manifest_hash']!=manifest_hash(raw):raise ValueError('manifest checksum')
    if raw['definition_hash']!=_hash(catalog.data):raise ValueError('universe checksum')
    expected={r['id'] for r in normal_planets()}
    if set(catalog.planets)!=expected:raise ValueError('48 planet coverage')
    coords={};cells=set()
    for row in raw['coordinates']:
        if set(row)!={'planet_id','x','y'} or row['planet_id'] not in expected or row['planet_id'] in coords:raise ValueError('coordinate reference')
        integer(row['x'],0,params['width']-1);integer(row['y'],0,params['height']-1)
        cell=(row['x'],row['y'])
        if cell in cells:raise ValueError('duplicate coordinate')
        coords[row['planet_id']]=cell;cells.add(cell)
    if set(coords)!=expected:raise ValueError('coordinates incomplete')
    def same(a,b):return canonical_bytes(a)==canonical_bytes(b)
    # Verify effective shared policies, independently of generator code or claimed inputs.
    for group in ('goods','ships','ship_grades','regional_prices'):
        a=copy.deepcopy(catalog.data.get(group));b=copy.deepcopy(source.data.get(group))
        if group in ('goods','ships'):
            for rows in (a,b):
                for row in rows:row.pop('name',None)
            a.sort(key=lambda r:r['id']);b.sort(key=lambda r:r['id'])
        if not same(a,b):raise ValueError('shared rule mismatch')
    for group in ('economy','production','development','industry_effects','market_events'):
        a={k:v for k,v in getattr(catalog,group).items() if k not in ('markets','sources','imports','planets','targets')}
        b={k:v for k,v in getattr(source,group).items() if k not in ('markets','sources','imports','planets','targets')}
        if modern and group=='development':b['mode']='linear_levels_v1'
        if not same(a,b):raise ValueError('shared policy mismatch')
    for key in ('cash','ship_id'):
        if catalog.data['starting'][key]!=source.data['starting'][key]:raise ValueError('starting rule mismatch')
    source_markets={(r['planet_id'],r['goods_id']):r for r in source.data['markets']}
    actual_markets={(r['planet_id'],r['goods_id']):r for r in catalog.data['markets']}
    def without_id(row):return {k:v for k,v in row.items() if k!='planet_id'}
    for pid in expected:
        dev=catalog.development_planets[pid]
        if modern:
            for ind,bounds in raw['industry_levels']['maximum_ranges'].items():
                maximum=dev['private_caps'][ind];initial=dev['initial_progress'][ind]
                integer(maximum,bounds['min'],bounds['max']);integer(initial,0,maximum)
                policy=raw['industry_levels']['initial_policy']
                if policy=='zero_v1' and initial!=0 or policy=='maximum_v1' and initial!=maximum:raise ValueError('initial policy mismatch')
        def matches(origin):
            base=source.development_planets[origin]
            if modern:
                if dev['resources']!=base['resources']:return False
            elif without_id(dev)!=without_id(base):return False
            if without_id(catalog.industry_effect_planets[pid])!=without_id(source.industry_effect_planets[origin]):return False
            actual_events=[without_id(r) for r in catalog.market_events.get('targets',[]) if r['planet_id']==pid]
            base_events=[without_id(r) for r in source.market_events.get('targets',[]) if r['planet_id']==origin]
            if actual_events!=base_events:return False
            for good in source.goods:
                key=(pid,good);old=(origin,good)
                if without_id(actual_markets[key])!=without_id(source_markets[old]):return False
                if without_id(catalog.economy_markets[key])!=without_id(source.economy_markets[old]):return False
                if catalog.production_imports.get(key,0)!=source.production_imports.get(old,0):return False
                a=catalog.production_sources.get(key);b=source.production_sources.get(old)
                if (a is None)!=(b is None):return False
                if a:
                    if a['industry']!=b['industry']:return False
                    low=max(1,b['units_per_tick']*params['production_percent_min']//100)
                    high=max(1,b['units_per_tick']*params['production_percent_max']//100)
                    if not low<=a['units_per_tick']<=high:return False
            return True
        if not any(matches(origin) for origin in source.planets):raise ValueError('planet rule binding')
    seen={catalog.data['starting']['planet_id']}
    for route in catalog.data['routes']:
        a,b=coords[route['from']],coords[route['to']];dist=abs(a[0]-b[0])+abs(a[1]-b[1])
        if route['distance']!=dist or dist>min(s['max_distance'] for s in source.ships.values()):raise ValueError('route distance')
        for ship in source.ships:
            base=next(r for (sid,_),r in source.navigation_plans.items() if sid==ship)
            plan=catalog.navigation_plans[ship,route['id']]
            time_factor=max(dist,(source.phase3 or {}).get('navigation_min_distance_units',1))
            if plan['normal_seconds']!=base['normal_seconds']*time_factor or plan['warp_options']!=[{**o,'seconds':o['seconds']*time_factor,'fuel_cost':o['fuel_cost']*dist} for o in base['warp_options']]:raise ValueError('navigation rule binding')
    while True:
        old=len(seen)
        for r in catalog.data['routes']:
            if r['from'] in seen or r['to'] in seen:seen.update((r['from'],r['to']))
        if len(seen)==old:break
    if seen!=expected:raise ValueError('disconnected universe')
    if connected:
        reached={catalog.data['starting']['planet_id']}
        while True:
            previous=len(reached)
            for route in catalog.data['routes']:
                if route['is_open'] and ({route['from'],route['to']} & reached):reached.update((route['from'],route['to']))
            if previous==len(reached):break
        if reached!=expected:raise ValueError('disconnected initial routes')
        if not any(not route['is_open'] for route in catalog.data['routes']):raise ValueError('missing donation routes')
    if sum(r['is_open'] for r in catalog.data['routes'])!=params['initial_open_routes']:raise ValueError('initial route count')


def rules(catalog):
    from .rules import effective_rules
    from .catalog import Catalog
    raw=catalog.data['universe']
    template_rules=effective_rules(Catalog(raw['template']))
    template_rules['starting'].pop('planet_id')
    template_rules.pop('routes')
    plans={row['ship_id']:{k:v for k,v in row.items() if k!='route_id'} for row in template_rules['navigation']}
    template_rules['navigation']=[plans[k] for k in sorted(plans)]
    extra={}
    if raw['format_version']>=2:
        template_rules['development']['mode']='linear_levels_v1'
        for row in template_rules['development']['planets']:
            row.pop('initial_progress');row.pop('private_caps')
        extra['industry_levels']=raw['industry_levels']
    return {**extra,'generator_version':raw['generator_version'],
            'normal_planet_ids':[r['id'] for r in normal_planets()],
            'parameters':{k:v for k,v in raw['parameters'].items() if k!='status'},
            'template_rules':template_rules}


def public_info(catalog):
    """Legacy trusted-local metadata, NOT a BBS disclosure projection (No.6).

    This includes the complete-definition digest. Use MasterService.manifest
    for a player-scoped BBS view; never distribute this catalog or its seed.
    """
    raw=catalog.data.get('universe')
    if raw is None:return None
    return {k:raw[k] for k in ('universe_id','generator_version','game_rules_version','definition_hash')}


def generate(*args,**kwargs):
    """Compatibility entry point for an explicitly invoked external tool only."""
    from srt_universe_generator.legacy import generate as external_generate
    return external_generate(*args,**kwargs)
